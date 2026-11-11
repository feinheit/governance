from django.test import TestCase

from governance.accounts.models import User
from governance.roles.models import Assignment, Role


class CircleMembersTest(TestCase):
    def setUp(self):
        self.ada = User.objects.create_user("ada@example.com", full_name="Ada")
        self.bob = User.objects.create_user("bob@example.com", full_name="Bob")
        self.eve = User.objects.create_user("eve@example.com", full_name="Eve")
        self.zoe = User.objects.create_user("zoe@example.com", full_name="Zoe")
        User.objects.create_user("old@example.com", full_name="Old", is_active=False)
        self.anchor = Role.objects.create(name="Example Ltd", is_circle=True)
        self.anchor.create_core_roles()
        self.kitchen = Role.objects.create(
            name="Kitchen", is_circle=True, circle=self.anchor
        )
        self.kitchen.create_core_roles()
        self.cook = Role.objects.create(name="Cook", circle=self.kitchen)
        self.dishwasher = Role.objects.create(name="Dishwasher", circle=self.kitchen)
        Assignment.objects.create(
            role=self.anchor.roles.get(core_role="lead"), user=self.ada
        )
        Assignment.objects.create(
            role=self.kitchen.roles.get(core_role="lead"), user=self.bob
        )
        Assignment.objects.create(role=self.kitchen, user=self.bob)
        Assignment.objects.create(role=self.cook, user=self.eve, focus="Soup")

    def test_members_and_others(self):
        self.client.force_login(self.zoe)
        url = f"/roles/{self.kitchen.pk}/members/"
        self.assertContains(self.client.get(self.kitchen.get_absolute_url()), url)

        response = self.client.get(url)
        # The circle above the title
        self.assertEqual(response.context["ancestors"], [self.anchor, self.kitchen])
        self.assertEqual(response.context["people"], [self.bob, self.eve])
        rows = {role.name: cells for role, cells in response.context["rows"]}
        # The core roles first, then the others
        self.assertEqual(
            list(rows),
            [
                "Circle Lead",
                "Facilitator",
                "Secretary",
                "Circle Rep",
                "Cook",
                "Dishwasher",
            ],
        )
        self.assertEqual(rows["Cook"][0], None)
        self.assertEqual(rows["Cook"][1]["assignment"].focus, "Soup")
        # Nobody holds the Dishwasher: the Circle Lead does (1.4.2), nobody
        # an unfilled Circle Rep
        self.assertEqual(rows["Dishwasher"], [{"stands_in": True}, None])
        self.assertEqual(rows["Circle Rep"], [None, None])
        self.assertContains(response, "Soup")
        # Active people who aren't members, also those without roles
        self.assertEqual(list(response.context["others"]), [self.ada, self.zoe])
        self.assertContains(response, self.zoe.get_absolute_url())

        # Only circles
        response = self.client.get(f"/roles/{self.cook.pk}/members/")
        self.assertEqual(response.status_code, 404)
