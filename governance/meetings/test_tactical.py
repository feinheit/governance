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

    def test_ad_hoc(self):
        """Any partner calls one and invites roles of any circle"""
        self.client.force_login(self.eve)
        response = self.client.get(f"/meetings/tactical/new/?role={self.cook.pk}")
        self.assertContains(response, "Cook (Kitchen)")
        self.client.post(
            "/meetings/tactical/new/",
            {"invited_roles": [self.cook.pk, self.sales.pk]},
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
