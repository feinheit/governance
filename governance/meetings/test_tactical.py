import datetime as dt

from django.core import mail
from django.test import TestCase
from django.utils import timezone

from governance.accounts.models import User
from governance.meetings.models import AgendaItem, Meeting
from governance.roles.models import Assignment, ChecklistItem, Link, Metric, Role


class TacticalTest(TestCase):
    def setUp(self):
        self.ada = User.objects.create_user("ada@example.com", full_name="Ada")
        self.bob = User.objects.create_user("bob@example.com", full_name="Bob")
        self.eve = User.objects.create_user("eve@example.com", full_name="Eve")
        self.anchor = Role.objects.create(name="Example Ltd", is_circle=True)
        self.anchor.create_core_roles()
        self.kitchen = Role.objects.create(
            name="Kitchen", is_circle=True, circle=self.anchor
        )
        self.kitchen.create_core_roles()
        self.cook = Role.objects.create(name="Cook", circle=self.kitchen)
        self.sales = Role.objects.create(name="Sales", circle=self.anchor)
        Assignment.objects.create(
            role=self.kitchen.roles.get(core_role="secretary"), user=self.ada
        )
        Assignment.objects.create(role=self.cook, user=self.bob)
        Assignment.objects.create(role=self.sales, user=self.eve)
        ChecklistItem.objects.create(role=self.cook, description="Fridge cleaned")
        # The kitchen's own item, for its own meetings, not the anchor's
        ChecklistItem.objects.create(role=self.kitchen, description="Kitchen tidy")
        Metric.objects.create(role=self.kitchen, description="Meals served")
        Metric.objects.create(role=self.sales, description="Offers sent")

    def test_sub_circles_own_items(self):
        """The anchor circle's meeting invites the kitchen's role, but not the
        kitchen's own items"""
        self.client.force_login(self.ada)
        Assignment.objects.create(
            role=self.anchor.roles.get(core_role="secretary"), user=self.ada
        )
        self.client.post(f"/roles/{self.anchor.pk}/meetings/new/", {"kind": "tactical"})
        meeting = Meeting.objects.get()
        self.assertIn(self.kitchen, meeting.invited_roles.all())
        self.client.post(f"/meetings/{meeting.pk}/step/", {"step": "checklists"})
        self.assertNotContains(
            self.client.get(meeting.get_absolute_url()), "Kitchen tidy"
        )
        self.assertNotContains(
            self.client.get(self.anchor.get_absolute_url()), "Kitchen tidy"
        )
        self.assertContains(
            self.client.get(self.kitchen.get_absolute_url()), "Kitchen tidy"
        )

    def test_regular(self):
        self.client.force_login(self.ada)
        self.client.post(
            f"/roles/{self.kitchen.pk}/meetings/new/", {"kind": "tactical"}
        )
        meeting = Meeting.objects.get()
        self.assertEqual(
            (meeting.kind, meeting.circle, meeting.called_by),
            (Meeting.TACTICAL, self.kitchen, self.ada),
        )
        self.assertIn(self.cook, meeting.invited_roles.all())
        response = self.client.get(meeting.get_absolute_url())
        self.assertNotContains(response, "Add proposal")
        # All of the circle's roles, the circle says it
        self.assertNotContains(response, "Invited roles")
        # In a modal, with their number
        self.assertContains(response, "Attendees (2)")
        self.assertNotContains(response, "Fridge cleaned")  # Only in its step

        # The reviews show the invited roles' entries (and the circle's own)
        self.client.post(f"/meetings/{meeting.pk}/step/", {"step": "checklists"})
        response = self.client.get(meeting.get_absolute_url())
        self.assertContains(response, "Fridge cleaned")
        self.assertContains(response, "Kitchen tidy")  # Its own meeting
        self.assertNotContains(response, "Meals served")
        self.client.post(f"/meetings/{meeting.pk}/step/", {"step": "metrics"})
        meeting.refresh_from_db()
        self.assertEqual(meeting.step, "metrics")
        response = self.client.get(meeting.get_absolute_url())
        self.assertContains(response, "Progress updates")
        self.assertContains(response, "Meals served")  # The circle's own
        self.assertNotContains(response, "Offers sent")
        self.assertNotContains(response, "Fridge cleaned")

        self.client.force_login(self.bob)
        self.client.post(f"/meetings/{meeting.pk}/agenda/add/", {"label": "Knives"})
        item = AgendaItem.objects.get()
        self.client.force_login(self.ada)
        self.client.post(f"/agenda/{item.pk}/process/")
        self.assertContains(self.client.get(meeting.get_absolute_url()), "Outcome")
        response = self.client.post(
            f"/agenda/{item.pk}/outcome/",
            {"outcome": "Bob buys new knives", "link": "javascript:alert(1)"},
            follow=True,
        )
        self.assertContains(response, "has to start with https://")
        self.client.post(
            f"/agenda/{item.pk}/outcome/",
            {
                "outcome": "Bob buys new knives",
                "link": "https://tasks.example.com/todos/3",
            },
        )
        item.refresh_from_db()
        self.assertTrue(item.is_completed)

        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(f"/meetings/{meeting.pk}/end/")
        self.assertEqual(
            sorted(m.to[0] for m in mail.outbox), ["ada@example.com", "bob@example.com"]
        )
        self.assertIn("Bob buys new knives", mail.outbox[0].body)
        self.assertIn("tasks.example.com", mail.outbox[0].body)

        # The next meeting's progress updates: the links of the circle and
        # its roles, and the outcomes of the earlier meetings to check on
        Link.objects.create(
            role=self.kitchen, title="Kitchen board", url="https://tasks.example.com/1"
        )
        Link.objects.create(
            role=self.sales, title="Sales board", url="https://tasks.example.com/2"
        )
        self.client.post(
            f"/roles/{self.kitchen.pk}/meetings/new/", {"kind": "tactical"}
        )
        meeting = Meeting.objects.running().get()
        self.client.post(f"/meetings/{meeting.pk}/step/", {"step": "progress"})
        response = self.client.get(meeting.get_absolute_url())
        self.assertContains(response, "Kitchen board")
        self.assertNotContains(response, "Sales board")  # Not invited
        self.assertContains(response, "Bob buys new knives")
        self.assertContains(response, 'href="https://tasks.example.com/todos/3"')

    def test_earlier_outcomes(self):
        """Progress updates show the last three tactical meetings' outcomes,
        "Show earlier meetings" ten, then ten more; the page's updates keep
        the number"""
        start = timezone.now() - dt.timedelta(days=30)
        for day in range(4):
            earlier = Meeting.objects.create(
                circle=self.kitchen,
                kind=Meeting.TACTICAL,
                started_at=start + dt.timedelta(days=day),
                ended_at=start + dt.timedelta(days=day, hours=1),
            )
            AgendaItem.objects.create(
                meeting=earlier, label=f"Item {day}", outcome=f"Outcome {day}"
            )
        meeting = Meeting.objects.create(
            circle=self.kitchen,
            kind=Meeting.TACTICAL,
            started_at=timezone.now(),
            step="progress",
        )
        url = meeting.get_absolute_url()
        self.client.force_login(self.ada)
        response = self.client.get(url)
        self.assertContains(response, "Outcome 3")
        self.assertNotContains(response, "Outcome 0")
        self.assertContains(response, 'href="?earlier=10#earlier-outcomes"')
        response = self.client.get(f"{url}?earlier=10")
        self.assertContains(response, "Outcome 0")
        self.assertNotContains(response, "Show earlier meetings")  # All of them
        self.assertContains(response, f'hx-get="{url}?earlier=10"')

    def test_followers_look_at_other_reviews(self):
        """Following, people look at another review on their own screen; the
        meeting stays where it is"""
        meeting = Meeting.objects.create(
            circle=self.kitchen,
            kind=Meeting.TACTICAL,
            started_at=timezone.now(),
            step="agenda",
            secretary=self.ada,
        )
        url = meeting.get_absolute_url()
        self.client.force_login(self.bob)  # Following
        response = self.client.get(url)
        self.assertContains(response, 'href="?step=metrics"')
        self.assertNotContains(response, 'href="?step=agenda"')  # No review
        self.assertNotContains(response, "Meals served")
        response = self.client.get(f"{url}?step=metrics")
        self.assertContains(response, "Meals served")
        self.assertContains(response, "the meeting is at")
        self.assertContains(response, f'hx-get="{url}?step=metrics"')
        meeting.refresh_from_db()
        self.assertEqual(meeting.step, "agenda")
        # Only reviews
        self.assertNotContains(
            self.client.get(f"{url}?step=closing"), "the meeting is at"
        )

    def test_outcome_autosaved(self):
        """The secretary's outcome saves itself while typing (without
        completing the item), the others see it"""
        meeting = Meeting.objects.create(
            circle=self.kitchen,
            kind=Meeting.TACTICAL,
            started_at=timezone.now(),
            secretary=self.ada,
            step="tensions",
        )
        item = AgendaItem.objects.create(meeting=meeting, label="Knives")
        meeting.current_item = item
        meeting.save()
        self.client.force_login(self.ada)
        response = self.client.post(
            f"/agenda/{item.pk}/outcome/",
            {"outcome": "Bob buys", "link": "https://tasks.example.com/4"},
            headers={"X-Autosave": "true"},
        )
        self.assertEqual(response.status_code, 204)
        item.refresh_from_db()
        self.assertEqual(
            (item.outcome, item.link, item.is_completed),
            ("Bob buys", "https://tasks.example.com/4", False),
        )
        self.client.force_login(self.bob)  # Following
        response = self.client.get(meeting.get_absolute_url())
        self.assertContains(response, "Bob buys")
        self.assertContains(response, 'href="https://tasks.example.com/4"')
        self.assertEqual(
            self.client.post(
                f"/agenda/{item.pk}/outcome/",
                {"outcome": "Mine"},
                headers={"X-Autosave": "true"},
            ).status_code,
            403,
        )

    def test_results_and_notes(self):
        """The results stack up beside the agenda (not in it, completed items
        are struck through there), the notes below save themselves"""
        meeting = Meeting.objects.create(
            circle=self.kitchen,
            kind=Meeting.TACTICAL,
            started_at=timezone.now(),
            secretary=self.ada,
            step="tensions",
        )
        AgendaItem.objects.create(
            meeting=meeting,
            label="Knives",
            position=1,
            outcome="Bob buys knives",
            is_completed=True,
        )
        forks = AgendaItem.objects.create(meeting=meeting, label="Forks", position=2)
        meeting.current_item = forks
        meeting.save()
        url = meeting.get_absolute_url()
        self.client.force_login(self.ada)
        response = self.client.get(url)
        self.assertContains(response, 'id="results"')
        self.assertContains(response, "Bob buys knives", count=1)  # Not in the agenda
        self.assertContains(response, "wb-completed")
        self.assertRegex(
            response.content.decode(),
            r'<form[^>]*action="/meetings/\d+/edit/"[^>]*data-autosave',
        )
        response = self.client.post(
            f"/meetings/{meeting.pk}/edit/",
            {"minutes": "Everybody was there"},
            headers={"X-Autosave": "true"},
        )
        self.assertEqual(response.status_code, 204)
        self.client.force_login(self.bob)  # Following
        response = self.client.get(url)
        self.assertContains(response, "Everybody was there")
        self.assertNotContains(response, 'name="minutes"')

    def test_reopen(self):
        """A completed item's agenda row leads to its result, the secretary
        reopens it there to correct it"""
        meeting = Meeting.objects.create(
            circle=self.kitchen,
            kind=Meeting.TACTICAL,
            started_at=timezone.now(),
            secretary=self.ada,
            step="tensions",
        )
        knives = AgendaItem.objects.create(
            meeting=meeting, label="Knives", outcome="Bob buys", is_completed=True
        )
        self.client.force_login(self.bob)  # Following
        response = self.client.get(meeting.get_absolute_url())
        self.assertContains(response, f'href="#result-{knives.pk}"')
        self.assertContains(response, f'id="result-{knives.pk}"')
        self.assertNotContains(response, f"/agenda/{knives.pk}/reopen/")
        self.assertEqual(
            self.client.post(f"/agenda/{knives.pk}/reopen/").status_code, 403
        )
        self.client.force_login(self.ada)
        self.assertContains(
            self.client.get(meeting.get_absolute_url()), f"/agenda/{knives.pk}/reopen/"
        )
        self.client.post(f"/agenda/{knives.pk}/reopen/")
        knives.refresh_from_db()
        meeting.refresh_from_db()
        self.assertEqual((knives.is_completed, meeting.current_item), (False, knives))

    def test_closing_round(self):
        """The closing round shows the notes and a large button to end the
        meeting, not the results"""
        meeting = Meeting.objects.create(
            circle=self.kitchen,
            kind=Meeting.TACTICAL,
            started_at=timezone.now(),
            secretary=self.ada,
            step="closing",
        )
        AgendaItem.objects.create(
            meeting=meeting, label="Knives", outcome="Bob buys", is_completed=True
        )
        self.client.force_login(self.ada)
        response = self.client.get(meeting.get_absolute_url())
        self.assertNotContains(response, "Bob buys")
        self.assertContains(response, 'name="minutes"')
        self.assertContains(response, "wb-end-meeting")
        self.client.force_login(self.bob)  # Following: the notes only
        response = self.client.get(meeting.get_absolute_url())
        self.assertNotContains(response, "wb-end-meeting")
        # Only while processing the tensions, not in the other steps
        for step, shown in [("check_in", False), ("agenda", False), ("tensions", True)]:
            Meeting.objects.filter(pk=meeting.pk).update(step=step)
            response = self.client.get(meeting.get_absolute_url())
            self.assertEqual("Bob buys" in response.content.decode(), shown, step)

    def test_active_item_only_while_processing(self):
        """Outside "Triage issues" no agenda item is active; processing one
        goes there"""
        meeting = Meeting.objects.create(
            circle=self.kitchen,
            kind=Meeting.TACTICAL,
            started_at=timezone.now(),
            secretary=self.ada,
            step="check_in",
        )
        knives = AgendaItem.objects.create(meeting=meeting, label="Knives", position=1)
        forks = AgendaItem.objects.create(meeting=meeting, label="Forks", position=2)
        meeting.current_item = knives
        meeting.save()
        self.client.force_login(self.ada)
        response = self.client.get(meeting.get_absolute_url())
        self.assertNotContains(response, 'id="current"')
        self.assertNotContains(response, "wb-current")
        self.client.post(f"/agenda/{forks.pk}/process/")
        meeting.refresh_from_db()
        self.assertEqual((meeting.step, meeting.current_item), ("tensions", forks))
        self.assertContains(self.client.get(meeting.get_absolute_url()), 'id="current"')

    def test_no_proposals(self):
        """Tactical meetings don't process proposals, not even crafted"""
        from governance.proposals.models import Proposal

        self.client.force_login(self.ada)
        self.client.post(
            f"/roles/{self.kitchen.pk}/meetings/new/", {"kind": "tactical"}
        )
        meeting = Meeting.objects.get()
        proposal = Proposal.objects.create(
            circle=self.kitchen,
            proposer=self.ada,
            tension="Knives",
            status=Proposal.PUBLISHED,
            created_at=meeting.started_at,
        )
        response = self.client.post(
            f"/meetings/{meeting.pk}/agenda/add/", {"proposal": proposal.pk}
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(meeting.agenda_items.exists())

    def test_ad_hoc_some_holders(self):
        """The caller may invite only some holders of a role (constitution
        3.1); an unfilled role's Circle Leads hold it"""
        zoe = User.objects.create_user("zoe@example.com", full_name="Zoe")
        Assignment.objects.create(role=self.cook, user=zoe)
        Assignment.objects.create(
            role=self.kitchen.roles.get(core_role="lead"), user=self.eve
        )
        waiter = Role.objects.create(name="Waiter", circle=self.kitchen)
        # Eve fills the unfilled Waiter as the kitchen's Circle Lead
        self.client.force_login(self.eve)
        response = self.client.get(
            f"/meetings/tactical/new/?role={self.cook.pk}&role={waiter.pk}"
        )
        for user in [self.bob, zoe]:
            self.assertRegex(
                response.content.decode(), rf'name="attendee"\s+value="{user.pk}"'
            )
        # The caller attends, unchecking isn't possible
        self.assertRegex(
            response.content.decode(),
            rf'name="attendee"\s+value="{self.eve.pk}"\s+checked\s+disabled',
        )
        self.client.post(
            "/meetings/tactical/new/",
            {
                "role": [self.cook.pk, waiter.pk],
                "attendee": [zoe.pk, self.bob.pk + 1000],
            },
        )
        meeting = Meeting.objects.get()
        self.assertEqual(set(meeting.invited_roles.all()), {self.cook, waiter})
        # The caller too, not who wasn't invited
        self.assertEqual(set(meeting.attendees.all()), {zoe, self.eve})
        # Without roles nothing
        self.client.post("/meetings/tactical/new/", {"attendee": [zoe.pk]})
        self.assertEqual(Meeting.objects.count(), 1)

    def test_ad_hoc_own_role(self):
        """The caller holds one of the roles at least, else the roles are
        chosen again"""
        self.client.force_login(self.ada)
        response = self.client.get(f"/meetings/tactical/new/?role={self.cook.pk}")
        self.assertContains(response, "You don&#x27;t hold any of these roles.")
        self.assertContains(response, "Next: who is invited")
        self.assertNotContains(response, "Start the meeting")
        response = self.client.post(
            "/meetings/tactical/new/",
            {"role": [self.cook.pk], "attendee": [self.bob.pk]},
        )
        self.assertContains(response, "You don&#x27;t hold any of these roles.")
        self.assertFalse(Meeting.objects.exists())

    def test_ad_hoc(self):
        """Any partner calls one and invites roles of any circle"""
        self.client.force_login(self.eve)
        # The roles, filtered in the browser, with their holders
        response = self.client.get("/meetings/tactical/new/")
        self.assertContains(response, "data-filter-rows")
        self.assertRegex(
            response.content.decode(), rf'name="role"\s+value="{self.cook.pk}"'
        )
        # Then who is invited
        response = self.client.get(
            f"/meetings/tactical/new/?role={self.cook.pk}&role={self.sales.pk}"
        )
        self.assertRegex(
            response.content.decode(), rf'name="attendee"\s+value="{self.bob.pk}"'
        )
        self.assertRegex(
            response.content.decode(), rf'name="attendee"\s+value="{self.eve.pk}"'
        )
        self.client.post(
            "/meetings/tactical/new/",
            {
                "role": [self.cook.pk, self.sales.pk],
                "attendee": [self.bob.pk, self.eve.pk],
            },
        )
        meeting = Meeting.objects.get()
        self.assertEqual((meeting.circle, meeting.called_by), (None, self.eve))
        self.assertEqual(set(meeting.attendees.all()), {self.bob, self.eve})
        self.client.post(f"/meetings/{meeting.pk}/step/", {"step": "checklists"})
        self.assertContains(
            self.client.get(meeting.get_absolute_url()), "Fridge cleaned"
        )
        self.client.post(f"/meetings/{meeting.pk}/step/", {"step": "metrics"})
        response = self.client.get(meeting.get_absolute_url())
        self.assertContains(response, "Offers sent")
        self.assertNotContains(response, "Meals served")  # Not invited
        self.assertContains(response, "Invited roles")  # Who was called
        self.assertContains(self.client.get(f"/people/{self.eve.pk}/"), "Your meetings")

        # She runs it, the invited Bob adds items, Ada neither
        meeting.refresh_from_db()
        self.assertTrue(meeting.is_running)
        self.client.force_login(self.bob)
        self.client.post(f"/meetings/{meeting.pk}/agenda/add/", {"label": "Leads"})
        self.assertEqual(
            self.client.post(f"/meetings/{meeting.pk}/end/").status_code, 403
        )
        self.client.force_login(self.ada)
        self.assertEqual(
            self.client.post(
                f"/meetings/{meeting.pk}/agenda/add/", {"label": "Hi"}
            ).status_code,
            403,
        )
        self.assertEqual(meeting.agenda_items.count(), 1)
        # No elections in tactical meetings
        self.client.force_login(self.eve)
        self.assertEqual(
            self.client.post(f"/meetings/{meeting.pk}/elections/", {}).status_code,
            403,
        )
