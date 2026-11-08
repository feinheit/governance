import datetime as dt
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from governance.accounts.models import User
from governance.meetings.models import Election, Meeting
from governance.roles.models import Assignment, Domain, Policy, Role


class LockingTest(TestCase):
    """Assignments, domain policies and elections wait for adoptions running
    at the same moment (``lock_structure()``) and check against their result:
    the fake lock archives the role like a proposal adopted meanwhile"""

    def setUp(self):
        self.ada = User.objects.create_user("ada@example.com", full_name="Ada")
        self.kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        self.kitchen.create_core_roles()
        Assignment.objects.create(
            role=self.kitchen.roles.get(core_role="lead"), user=self.ada
        )
        self.cook = Role.objects.create(name="Cook", circle=self.kitchen)
        self.client.force_login(self.ada)

    def adopted_meanwhile(self, role):
        def archive():
            Role.objects.filter(pk=role.pk).update(archived_on=timezone.localdate())

        return mock.patch("governance.locking.lock_structure", side_effect=archive)

    def test_assignment(self):
        with self.adopted_meanwhile(self.cook):
            response = self.client.post(
                f"/roles/{self.cook.pk}/assignments/", {"user": self.ada.pk}
            )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Assignment.objects.filter(role=self.cook).exists())

    def test_domain_policy(self):
        domain = Domain.objects.create(role=self.cook, text="The stove")
        with self.adopted_meanwhile(self.cook):
            response = self.client.post(
                f"/roles/{self.cook.pk}/domain-policies/new/",
                {"title": "Off at night", "body": "", "domain": domain.pk},
            )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Policy.objects.exists())

    def test_election(self):
        facilitator = self.kitchen.roles.get(core_role="facilitator")
        meeting = Meeting.objects.create(
            circle=self.kitchen,
            kind=Meeting.GOVERNANCE,
            secretary=self.ada,
            started_at=timezone.now(),
        )
        meeting.attendees.add(self.ada)
        with self.adopted_meanwhile(facilitator):
            response = self.client.post(
                f"/meetings/{meeting.pk}/elections/",
                {
                    "role": facilitator.pk,
                    "user": self.ada.pk,
                    "term_ends_on": timezone.localdate() + dt.timedelta(days=30),
                },
            )
        self.assertRedirects(response, meeting.get_absolute_url())
        self.assertFalse(Election.objects.exists())
