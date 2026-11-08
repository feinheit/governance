from django.test import TestCase

from governance.accounts.models import User
from governance.roles.models import Assignment, Role


class MailAddressesTest(TestCase):
    def test_groups(self):
        """The addresses of the core roles in all circles, with who stands
        in, and of each circle's members"""
        ada = User.objects.create_user("ada@example.com", full_name="Ada Lovelace")
        bob = User.objects.create_user("bob@example.com", full_name="Bob Müller")
        eve = User.objects.create_user("eve@example.com", full_name="Eve, Kitchen")
        gone = User.objects.create_user("gone@example.com", is_active=False)
        company = Role.objects.create(name="Company", is_circle=True)
        company.create_core_roles()
        kitchen = Role.objects.create(name="Kitchen", is_circle=True, circle=company)
        kitchen.create_core_roles()
        for role, user in [
            (company.roles.get(core_role="lead"), ada),
            (company.roles.get(core_role="secretary"), bob),
            (kitchen.roles.get(core_role="lead"), eve),
            (Role.objects.create(name="Cook", circle=kitchen), gone),
        ]:
            Assignment.objects.create(role=role, user=user)
        self.client.force_login(ada)

        response = self.client.get("/people/addresses/")
        groups = {g["key"]: g for g in response.context["groups"]}
        circles = {g["key"]: g for g in response.context["circle_groups"]}
        self.assertEqual(
            groups["everybody"]["addresses"],
            # Readable, not encoded for headers; quoted where needed
            "Ada Lovelace <ada@example.com>, Bob Müller <bob@example.com>, "
            '"Eve, Kitchen" <eve@example.com>',
        )
        self.assertEqual(groups["circle-leads"]["users"], [ada, eve])
        # Bob in the company; the kitchen has none, its Circle Lead stands in
        self.assertEqual(groups["secretaries"]["users"], [bob, eve])
        # The company's Secretary stands in for its Facilitator
        self.assertEqual(groups["facilitators"]["users"], [bob, eve])
        self.assertEqual(groups["circle-reps"]["users"], [])
        self.assertEqual(circles[f"circle-{kitchen.pk}"]["users"], [eve])
        self.assertContains(response, "mailto:ada@example.com,bob@example.com")

        # The circle's menu links its members
        self.assertContains(
            self.client.get(kitchen.get_absolute_url()),
            f"/people/addresses/#circle-{kitchen.pk}",
        )
