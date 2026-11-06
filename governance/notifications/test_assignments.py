import datetime as dt

import time_machine
from django.core import mail
from django.test import TestCase
from django.utils import timezone

from governance.accounts.models import User
from governance.meetings.elections import record_election
from governance.meetings.models import Meeting
from governance.roles.assignments import end_assignments_of
from governance.roles.models import Assignment, Role


@time_machine.travel(dt.datetime(2026, 12, 1, 12), tick=False)
class AssignmentMailsTest(TestCase):
    """People hear about roles they get and lose, the circle's Secretaries
    about people joining and leaving the circle (like GlassFrog)"""

    def setUp(self):
        self.ada = User.objects.create_user("ada@example.com", full_name="Ada")
        self.bob = User.objects.create_user("bob@example.com", full_name="Bob")
        self.eve = User.objects.create_user("eve@example.com", full_name="Eve")
        self.kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        self.kitchen.create_core_roles()
        self.cook = Role.objects.create(name="Cook", circle=self.kitchen)
        self.waiter = Role.objects.create(name="Waiter", circle=self.kitchen)
        started = dt.date(2026, 1, 1)
        Assignment.objects.create(
            role=self.kitchen.roles.get(core_role="lead"),
            user=self.ada,
            starts_on=started,
        )
        Assignment.objects.create(
            role=self.kitchen.roles.get(core_role="secretary"),
            user=self.bob,
            starts_on=started,
        )

    def outbox(self):
        sent = sorted((m.to[0], m.subject) for m in mail.outbox)
        mail.outbox = []
        return sent

    def test_assigning_and_removing(self):
        self.client.force_login(self.ada)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                f"/roles/{self.cook.pk}/assignments/", {"user": self.eve.pk}
            )
        self.assertEqual(
            self.outbox(),
            [
                ("bob@example.com", "Members of Kitchen: Eve joined"),
                ("eve@example.com", "Your roles: Cook (Kitchen)"),
            ],
        )
        # Another role in the same circle: no change of members
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                f"/roles/{self.waiter.pk}/assignments/", {"user": self.eve.pk}
            )
        self.assertEqual(
            self.outbox(), [("eve@example.com", "Your roles: Waiter (Kitchen)")]
        )
        Assignment.objects.update(starts_on=dt.date(2026, 6, 1))
        for role in [self.cook, self.waiter]:
            assignment = Assignment.objects.get(role=role, user=self.eve)
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(f"/assignments/{assignment.pk}/end/")
        self.assertEqual(
            self.outbox(),
            [
                ("bob@example.com", "Members of Kitchen: Eve left"),
                ("eve@example.com", "Your roles: no longer Cook (Kitchen)"),
                ("eve@example.com", "Your roles: no longer Waiter (Kitchen)"),
            ],
        )

    def test_election(self):
        facilitator = self.kitchen.roles.get(core_role="facilitator")
        meeting = Meeting.objects.create(
            circle=self.kitchen, kind=Meeting.GOVERNANCE, started_at=timezone.now()
        )
        with self.captureOnCommitCallbacks(execute=True):
            record_election(meeting, facilitator, self.eve, dt.date(2027, 12, 1))
        self.assertEqual(
            self.outbox(),
            [
                ("bob@example.com", "Members of Kitchen: Eve joined"),
                ("eve@example.com", "Your roles: Facilitator (Kitchen)"),
            ],
        )

    def test_deactivated_people_get_nothing(self):
        Assignment.objects.create(
            role=self.cook, user=self.eve, starts_on=dt.date(2026, 1, 1)
        )
        self.eve.is_active = False
        self.eve.save()
        with self.captureOnCommitCallbacks(execute=True):
            end_assignments_of(self.eve, timezone.localdate())
        self.assertEqual(
            self.outbox(), [("bob@example.com", "Members of Kitchen: Eve left")]
        )
