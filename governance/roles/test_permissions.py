from django.test import TestCase

from governance.accounts.models import User
from governance.roles.models import Assignment, Role
from governance.roles.permissions import (
    can_assign,
    can_lead,
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
