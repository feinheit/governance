import datetime as dt

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from governance.accounts.models import User
from governance.meetings.models import AgendaItem, Meeting
from governance.roles.models import Assignment, Role


class MeetingsTest(TestCase):
    def setUp(self):
        self.ada = User.objects.create_user("ada@example.com", full_name="Ada")
        self.bob = User.objects.create_user("bob@example.com", full_name="Bob")
        self.eve = User.objects.create_user("eve@example.com", full_name="Eve")
        self.kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        self.kitchen.create_core_roles()
        self.cook = Role.objects.create(name="Cook", circle=self.kitchen)
        Assignment.objects.create(
            role=self.kitchen.roles.get(core_role="facilitator"), user=self.ada
        )
        Assignment.objects.create(
            role=self.kitchen.roles.get(core_role="secretary"), user=self.bob
        )
        Assignment.objects.create(role=self.cook, user=self.eve)

    def test_lifecycle(self):
        self.client.force_login(self.bob)
        response = self.client.get(f"/roles/{self.kitchen.pk}/")
        self.assertContains(response, "Start a governance meeting")
        response = self.client.post(f"/roles/{self.kitchen.pk}/meetings/new/")
        meeting = Meeting.objects.get()
        self.assertRedirects(response, meeting.get_absolute_url())
        self.assertEqual(
            (meeting.kind, meeting.secretary), (Meeting.GOVERNANCE, self.bob)
        )
        # Calling a meeting starts it
        self.assertTrue(meeting.is_running)
        # The rounds around the agenda (constitution 5.4.3)
        self.assertContains(
            self.client.get(meeting.get_absolute_url()), "Check-in round"
        )
        self.client.post(f"/meetings/{meeting.pk}/step/", {"step": "closing"})
        meeting.refresh_from_db()
        self.assertEqual(meeting.step, "closing")
        self.client.post(
            f"/meetings/{meeting.pk}/step/", {"step": "metrics"}
        )  # Tactical only
        meeting.refresh_from_db()
        self.assertEqual(meeting.step, "closing")
        self.assertContains(self.client.get(f"/roles/{self.kitchen.pk}/"), "running")

        self.client.post(f"/meetings/{meeting.pk}/edit/", {"minutes": "Tea"})
        meeting.refresh_from_db()
        self.assertEqual(meeting.minutes, "Tea")

        self.client.post(f"/meetings/{meeting.pk}/end/")
        meeting.refresh_from_db()
        self.assertFalse(meeting.is_running)
        self.assertIsNotNone(meeting.ended_at)

    def test_one_running_meeting_per_circle(self):
        self.client.force_login(self.bob)
        self.client.post(f"/roles/{self.kitchen.pk}/meetings/new/")
        meeting = Meeting.objects.get()
        # Starting another one joins the running one
        response = self.client.post(
            f"/roles/{self.kitchen.pk}/meetings/new/", {"kind": "tactical"}
        )
        self.assertRedirects(response, meeting.get_absolute_url())
        self.assertEqual(Meeting.objects.count(), 1)
        response = self.client.get(f"/roles/{self.kitchen.pk}/")
        self.assertNotContains(response, "Start a tactical meeting")
        self.assertContains(response, "Join the running meeting")

        # Ad-hoc tactical meetings have no circle, they may run at any time
        response = self.client.post(
            "/meetings/tactical/new/", {"invited_roles": [self.cook.pk]}
        )
        self.assertEqual(Meeting.objects.filter(ended_at=None).count(), 2)

        # After the end, the next one
        self.client.post(f"/meetings/{meeting.pk}/end/")
        self.client.post(
            f"/roles/{self.kitchen.pk}/meetings/new/", {"kind": "tactical"}
        )
        self.assertEqual(Meeting.objects.count(), 3)

    def test_inactive_meetings_end(self):
        self.client.force_login(self.bob)
        self.client.post(f"/roles/{self.kitchen.pk}/meetings/new/")
        meeting = Meeting.objects.get()
        self.assertIsNotNone(meeting.active_at)
        # Changes in the meeting are activity
        Meeting.objects.update(active_at=timezone.now() - dt.timedelta(hours=1))
        self.client.post(f"/meetings/{meeting.pk}/agenda/add/", {"label": "Tea"})
        meeting.refresh_from_db()
        self.assertGreater(meeting.active_at, timezone.now() - dt.timedelta(minutes=1))

        call_command("fairy_tasks")
        meeting.refresh_from_db()
        self.assertTrue(meeting.is_running)

        # Inactive for hours: it ended with its last activity (hourly, and
        # in fairy_tasks)
        last = timezone.now() - dt.timedelta(hours=4)
        Meeting.objects.update(active_at=last)
        call_command("end_inactive_meetings")
        meeting.refresh_from_db()
        self.assertEqual(meeting.ended_at, last)

    def test_starting_ends_an_inactive_meeting(self):
        self.client.force_login(self.bob)
        self.client.post(f"/roles/{self.kitchen.pk}/meetings/new/")
        stale = Meeting.objects.get()
        Meeting.objects.update(active_at=timezone.now() - dt.timedelta(hours=4))
        self.client.post(f"/roles/{self.kitchen.pk}/meetings/new/")
        stale.refresh_from_db()
        self.assertFalse(stale.is_running)
        self.assertTrue(Meeting.objects.latest("pk").is_running)

    def test_running_meetings_banner(self):
        self.client.force_login(self.bob)
        self.client.post(f"/roles/{self.kitchen.pk}/meetings/new/")
        meeting = Meeting.objects.get()
        banner = "Running now:"
        # Attendees see it on every page, except in the meeting itself
        self.assertContains(self.client.get("/people/"), banner)
        self.assertNotContains(self.client.get(meeting.get_absolute_url()), banner)
        meeting.attendees.remove(self.eve)
        self.client.force_login(self.eve)
        self.assertNotContains(self.client.get("/people/"), banner)
        # Not when it's inactive, it ends soon
        self.client.force_login(self.bob)
        Meeting.objects.update(active_at=timezone.now() - dt.timedelta(hours=4))
        self.assertNotContains(self.client.get("/people/"), banner)

    def test_stand_ins(self):
        """Without a Secretary the Facilitator stands in, then the Circle Lead,
        then whoever starts the meeting (constitution 5.3.6)"""
        Assignment.objects.filter(role__core_role="secretary").delete()
        self.client.force_login(self.eve)
        self.client.post(f"/roles/{self.kitchen.pk}/meetings/new/")
        meeting = Meeting.objects.get()
        self.assertEqual(meeting.secretary, self.ada)
        meeting.ended_at = timezone.now()
        meeting.save()
        Assignment.objects.filter(role__core_role="facilitator").delete()
        self.client.post(f"/roles/{self.kitchen.pk}/meetings/new/")
        meeting = Meeting.objects.latest("pk")
        self.assertEqual(meeting.secretary, self.eve)

    def test_take_over_as_secretary(self):
        """Anybody running the meeting takes over as its secretary, a warning
        asks those who aren't the circle's Secretary first"""
        self.client.force_login(self.bob)
        self.client.post(f"/roles/{self.kitchen.pk}/meetings/new/")
        meeting = Meeting.objects.get()
        self.assertNotContains(self.client.get(meeting.get_absolute_url()), "Take over")
        self.client.force_login(self.eve)
        response = self.client.get(meeting.get_absolute_url())
        self.assertContains(response, "Take over")
        self.assertContains(response, "hx-confirm=")
        self.client.post(f"/meetings/{meeting.pk}/secretary/")
        meeting.refresh_from_db()
        self.assertEqual(meeting.secretary, self.eve)
        # The circle's Secretary takes over again without a warning
        self.client.force_login(self.bob)
        response = self.client.get(meeting.get_absolute_url())
        self.assertContains(response, "Take over")
        self.assertNotContains(response, "hx-confirm=")
        self.client.post(f"/meetings/{meeting.pk}/secretary/")
        meeting.refresh_from_db()
        self.assertEqual(meeting.secretary, self.bob)
        outsider = User.objects.create_user("max@example.com")
        self.client.force_login(outsider)
        self.assertEqual(
            self.client.post(f"/meetings/{meeting.pk}/secretary/").status_code, 403
        )

    def test_permissions_and_list(self):
        # Members stand in for the Facilitator and Secretary (5.3.6), others
        # don't run the circle's meetings
        self.client.force_login(self.eve)
        self.assertContains(
            self.client.get(f"/roles/{self.kitchen.pk}/"), "Start a governance meeting"
        )
        outsider = User.objects.create_user("max@example.com", full_name="Max")
        self.client.force_login(outsider)  # Not a member of the circle
        self.assertNotContains(
            self.client.get(f"/roles/{self.kitchen.pk}/"), "Start a governance meeting"
        )
        self.assertEqual(
            self.client.post(f"/roles/{self.kitchen.pk}/meetings/new/").status_code,
            403,
        )
        imported = Meeting.objects.create(
            circle=self.kitchen,
            kind=Meeting.TACTICAL,
            started_at=timezone.now(),
            glassfrog_id=1,
        )
        AgendaItem.objects.create(meeting=imported, label="Dishes", owner=self.ada)
        unknown = Meeting.objects.create(kind=Meeting.GOVERNANCE, glassfrog_id=2)
        response = self.client.get(f"/roles/{self.kitchen.pk}/meetings/?kind=tactical")
        self.assertContains(response, imported.get_absolute_url())
        self.assertContains(self.client.get(imported.get_absolute_url()), "Dishes")
        self.assertEqual(self.client.get(unknown.get_absolute_url()).status_code, 200)
        self.assertEqual(
            self.client.post(f"/meetings/{imported.pk}/end/").status_code, 403
        )
        self.assertEqual(
            self.client.post(f"/meetings/{unknown.pk}/end/").status_code, 403
        )

    def test_agenda_only_in_the_meeting(self):
        """The agenda is built in the meeting, not before or after (5.4.4)"""
        meeting = Meeting.objects.create(
            circle=self.kitchen, kind=Meeting.GOVERNANCE, ended_at=timezone.now()
        )
        self.client.force_login(self.eve)
        self.client.post(f"/meetings/{meeting.pk}/agenda/add/", {"label": "Dishes"})
        self.assertFalse(meeting.agenda_items.exists())

    def test_agenda(self):
        from governance.proposals.models import Proposal

        meeting = Meeting.objects.create(
            circle=self.kitchen, kind=Meeting.GOVERNANCE, started_at=timezone.now()
        )
        draft = Proposal.objects.create(
            circle=self.kitchen,
            proposer=self.eve,
            tension="More salt",
            created_at=timezone.now(),
        )
        waiting = Proposal.objects.create(
            circle=self.kitchen,
            proposer=self.ada,
            tension="Objected",
            status=Proposal.IN_MEETING,
            created_at=timezone.now(),
        )
        published = Proposal.objects.create(
            circle=self.kitchen,
            proposer=self.ada,
            tension="Async",
            status=Proposal.PUBLISHED,
            created_at=timezone.now(),
            published_at=timezone.now(),
            deadline=timezone.now(),
        )
        url = f"/meetings/{meeting.pk}/agenda/add/"
        self.client.force_login(self.eve)
        self.assertContains(self.client.get(meeting.get_absolute_url()), "Async")
        self.client.post(url, {"proposal": published.pk})
        published.refresh_from_db()
        # Brought into the meeting, the async process ends
        self.assertEqual(
            (published.status, published.meeting), (Proposal.IN_MEETING, meeting)
        )
        meeting.agenda_items.all().delete()
        response = self.client.get(meeting.get_absolute_url())
        self.assertContains(response, "More salt")  # Her own draft
        self.assertContains(response, "Objected")
        self.client.post(url, {"label": "Dishes"})
        self.client.post(url, {"proposal": draft.pk})
        self.client.post(url, {"proposal": waiting.pk})
        draft.refresh_from_db()
        self.assertEqual((draft.status, draft.meeting), (Proposal.IN_MEETING, meeting))
        self.assertEqual(
            list(meeting.agenda_items.values_list("label", "position")),
            [("Dishes", 1), ("More salt", 2), ("Objected", 3)],
        )
        response = self.client.get(meeting.get_absolute_url())
        self.assertContains(response, "Dishes")
        self.assertContains(response, "Move up")  # Members may run it

        # Ada's own draft isn't offered to Eve
        other = Proposal.objects.create(
            circle=self.kitchen,
            proposer=self.ada,
            tension="Secret",
            created_at=timezone.now(),
        )
        self.assertEqual(self.client.post(url, {"proposal": other.pk}).status_code, 404)

        self.client.force_login(self.bob)  # The Secretary
        items = list(meeting.agenda_items.all())
        self.client.post(f"/agenda/{items[2].pk}/move/", {"direction": "up"})
        self.assertEqual(
            list(meeting.agenda_items.values_list("label", flat=True)),
            ["Dishes", "Objected", "More salt"],
        )
        self.client.post(f"/agenda/{items[0].pk}/remove/")
        self.assertEqual(meeting.agenda_items.count(), 2)

        # Not a member
        outsider = User.objects.create_user("zoe@example.com")
        self.client.force_login(outsider)
        self.assertEqual(self.client.post(url, {"label": "Hi"}).status_code, 403)
        self.assertEqual(
            self.client.post(f"/agenda/{items[1].pk}/remove/").status_code, 403
        )

    def test_attendees(self):
        self.client.force_login(self.bob)
        self.client.post(f"/roles/{self.kitchen.pk}/meetings/new/")
        meeting = Meeting.objects.get()
        # The circle's members by default
        self.assertEqual(set(meeting.attendees.all()), {self.ada, self.bob, self.eve})
        guest = User.objects.create_user("zoe@example.com", full_name="Zoe")
        url = f"/meetings/{meeting.pk}/attendees/"
        self.client.post(url, {"user": guest.pk, "action": "add"})
        self.client.post(url, {"user": self.eve.pk, "action": "remove"})
        self.assertEqual(set(meeting.attendees.all()), {self.ada, self.bob, guest})
        self.assertContains(self.client.get(meeting.get_absolute_url()), "Zoe")

        # Guests add agenda items too
        self.client.force_login(guest)
        self.client.post(f"/meetings/{meeting.pk}/agenda/add/", {"label": "Hello"})
        self.assertEqual(meeting.agenda_items.get().label, "Hello")
        self.assertEqual(
            self.client.post(url, {"user": guest.pk, "action": "remove"}).status_code,
            403,
        )
