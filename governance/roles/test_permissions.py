from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from governance.accounts.models import User
from governance.meetings.access import can_run
from governance.meetings.models import Meeting
from governance.roles.domain_policies import can_change_domain_policies
from governance.roles.models import Assignment, Domain, Role
from governance.roles.permissions import (
    ALLOWED,
    AS_ADMIN,
    AS_SECRETARY,
    NOT_ALLOWED,
    can_assign,
    can_change_settings,
    can_end_assignment,
    can_lead,
    can_start_meeting,
    circle_leads,
    is_member,
    proposer_roles,
)


class CircleLeadsTest(TestCase):
    def test_unfilled_circle_lead(self):
        """While nobody leads a circle, the super-circle's Circle Leads do,
        all of them (1.4.2: they lead the unfilled role, so its circle)"""
        ada = User.objects.create_user("ada@example.com", full_name="Ada")
        bob = User.objects.create_user("bob@example.com", full_name="Bob")
        eve = User.objects.create_user("eve@example.com", full_name="Eve")
        anchor = Role.objects.create(name="Example Ltd", is_circle=True)
        anchor.create_core_roles()
        kitchen = Role.objects.create(name="Kitchen", is_circle=True, circle=anchor)
        kitchen.create_core_roles()
        bakery = Role.objects.create(name="Bakery", is_circle=True, circle=kitchen)
        bakery.create_core_roles()
        baker = Role.objects.create(name="Baker", circle=bakery)
        kitchen_lead = kitchen.roles.get(core_role="lead")
        Assignment.objects.create(role=kitchen_lead, user=ada)
        Assignment.objects.create(role=kitchen_lead, user=bob)

        # Two levels down, nobody leads the bakery: the kitchen's leads do
        self.assertEqual(set(circle_leads(bakery)), {ada, bob})
        self.assertTrue(can_lead(bob, bakery))
        self.assertTrue(can_assign(bob, baker))
        self.assertTrue(is_member(bob, bakery))
        self.assertIn(baker, proposer_roles(bob, bakery))
        self.assertFalse(can_lead(eve, bakery))
        # Pages show who covers unfilled roles
        self.client.force_login(eve)
        response = self.client.get(baker.get_absolute_url())
        self.assertContains(response, "the Circle Leads (by default)")
        self.assertContains(response, ada.get_absolute_url())
        self.assertContains(response, bob.get_absolute_url())
        response = self.client.get(
            bakery.roles.get(core_role="lead").get_absolute_url()
        )
        self.assertContains(response, "the super-circle's Circle Leads")
        self.assertContains(response, bob.get_absolute_url())
        self.assertContains(
            self.client.get(bakery.get_absolute_url()), "Held by the Circle Leads"
        )

        # Once somebody leads the bakery, they do
        Assignment.objects.create(role=bakery.roles.get(core_role="lead"), user=eve)
        self.assertEqual(set(circle_leads(bakery)), {eve})
        self.assertFalse(can_lead(bob, bakery))
        self.assertTrue(can_lead(eve, bakery))
        # The anchor circle has no Circle Leads unless assigned (1.4)
        self.assertEqual(list(circle_leads(anchor)), [])


class ElevatedRightsTest(TestCase):
    """The checks say why somebody may do something; doing what the
    constitution leaves to others, as admin or as Secretary standing in
    for the Circle Leads, is marked on the buttons and explained in the
    forms"""

    def setUp(self):
        self.lead = User.objects.create_user("lead@example.com", full_name="Lea")
        self.secretary = User.objects.create_user("sec@example.com", full_name="Sec")
        self.admin = User.objects.create_user(
            "admin@example.com", full_name="Adi", is_admin=True
        )
        self.anchor = Role.objects.create(name="Example Ltd", is_circle=True)
        self.anchor.create_core_roles()
        self.kitchen = Role.objects.create(
            name="Kitchen", is_circle=True, circle=self.anchor
        )
        self.kitchen.create_core_roles()
        self.cook = Role.objects.create(name="Cook", circle=self.kitchen)
        Domain.objects.create(role=self.cook, text="The stove")
        Assignment.objects.create(
            role=self.kitchen.roles.get(core_role="lead"), user=self.lead
        )
        Assignment.objects.create(
            role=self.kitchen.roles.get(core_role="secretary"), user=self.secretary
        )
        self.assignment = Assignment.objects.create(role=self.cook, user=self.lead)

    def test_rights(self):
        self.assertEqual(can_lead(self.lead, self.kitchen), ALLOWED)
        self.assertEqual(can_lead(self.secretary, self.kitchen), AS_SECRETARY)
        self.assertEqual(can_lead(self.admin, self.kitchen), AS_ADMIN)
        self.assertEqual(can_assign(self.secretary, self.cook), AS_SECRETARY)
        self.assertEqual(can_change_settings(self.secretary, self.cook), ALLOWED)
        self.assertEqual(can_change_settings(self.admin, self.cook), AS_ADMIN)
        self.assertEqual(can_change_settings(self.lead, self.cook), NOT_ALLOWED)
        self.assertEqual(can_change_domain_policies(self.lead, self.cook), ALLOWED)
        self.assertEqual(can_change_domain_policies(self.admin, self.cook), AS_ADMIN)
        self.assertEqual(can_start_meeting(self.lead, self.kitchen), ALLOWED)
        self.assertEqual(can_start_meeting(self.admin, self.kitchen), AS_ADMIN)
        # Nobody leads the anchor circle: only admins end its assignments
        facilitator = self.anchor.roles.get(core_role="facilitator")
        Assignment.objects.create(role=facilitator, user=self.admin)
        self.assertEqual(can_end_assignment(self.admin, facilitator), AS_ADMIN)
        self.assertEqual(can_end_assignment(self.lead, facilitator), NOT_ALLOWED)

    def test_pages(self):
        end_url = reverse("assignment_end", kwargs={"pk": self.assignment.pk})
        self.client.force_login(self.lead)
        response = self.client.get(self.cook.get_absolute_url())
        self.assertContains(response, "btn-destructive")  # Remove
        self.assertNotContains(response, "btn-elevated")
        self.assertNotContains(self.client.get(end_url), "alert-warning")

        self.client.force_login(self.secretary)
        response = self.client.get(self.cook.get_absolute_url())
        self.assertContains(
            response, 'title="As Secretary, standing in for the Circle Leads"'
        )
        self.assertContains(
            self.client.get(end_url),
            "You can do this as Secretary, standing in for the Circle Leads",
        )

        self.client.force_login(self.admin)
        response = self.client.get(self.cook.get_absolute_url())
        self.assertContains(response, 'btn-elevated" title="As admin"')
        self.assertContains(self.client.get(end_url), "You can do this as an admin")
        self.assertContains(
            self.client.get(reverse("role_strategy", kwargs={"pk": self.kitchen.pk})),
            "You can do this as an admin",
        )
        self.assertContains(
            self.client.get(reverse("meeting_create", kwargs={"pk": self.kitchen.pk})),
            "You can do this as an admin",
        )
        meeting = Meeting.objects.create(
            circle=self.kitchen, kind=Meeting.GOVERNANCE, started_at=timezone.now()
        )
        self.assertEqual(can_run(self.admin, meeting), AS_ADMIN)
        self.assertContains(
            self.client.get(meeting.get_absolute_url()),
            "You run this meeting as an admin",
        )
