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
        # A line below the last core role
        self.assertEqual(
            [
                role.name
                for role, _cells in response.context["rows"]
                if getattr(role, "last_core", False)
            ],
            ["Circle Rep"],
        )
        self.assertContains(response, 'class="wb-matrix-last-core"', count=1)
        # Two others: room after the last column for the label above them
        self.assertContains(response, "wb-matrix-label-room")
        User.objects.create_user("max@example.com", full_name="Max")
        self.assertNotContains(self.client.get(url), "wb-matrix-label-room")

        def marks(cells):
            return [
                cell["assignment"].focus
                if cell["assignment"]
                else "stands in"
                if cell["stands_in"]
                else None
                for cell in cells
            ]

        # Bob and Eve, then the active people who aren't members (also
        # those without roles) as columns on the right
        self.assertEqual(marks(rows["Cook"]), [None, "Soup", None, None])
        # Nobody holds the Dishwasher: the Circle Lead does (1.4.2), nobody
        # an unfilled Circle Rep
        self.assertEqual(marks(rows["Dishwasher"]), ["stands in", None, None, None])
        self.assertEqual(marks(rows["Circle Rep"]), [None, None, None, None])
        self.assertContains(response, "Soup")
        self.assertEqual(list(response.context["others"]), [self.ada, self.zoe])
        self.assertContains(response, self.zoe.get_absolute_url())

        # Only circles
        response = self.client.get(f"/roles/{self.cook.pk}/members/")
        self.assertEqual(response.status_code, 404)

    def test_tools(self):
        url = f"/roles/{self.kitchen.pk}/members/"
        cook = Assignment.objects.get(role=self.cook)
        tools = [
            f"/assignments/{cook.pk}/?next={url}",  # Edit focus
            f"/assignments/{cook.pk}/end/?next={url}",
            # Bob holds the unfilled Dishwasher as Circle Lead
            f"/roles/{self.dishwasher.pk}/assignments/?user={self.bob.pk}&amp;next={url}",
            f"/roles/{self.cook.pk}/assignments/?user={self.bob.pk}&amp;next={url}",
            # Also people who aren't members yet
            f"/roles/{self.cook.pk}/assignments/?user={self.zoe.pk}&amp;next={url}",
        ]
        self.client.force_login(self.zoe)
        response = self.client.get(url)
        for tool in tools:
            self.assertNotContains(response, tool)

        self.client.force_login(self.bob)  # The Circle Lead
        response = self.client.get(url)
        for tool in tools:
            self.assertContains(response, tool)
        # Elected roles aren't assigned here
        facilitator = self.kitchen.roles.get(core_role="facilitator")
        self.assertNotContains(response, f"/roles/{facilitator.pk}/assignments/")

        # The form preselects the person
        response = self.client.get(
            f"/roles/{self.cook.pk}/assignments/?user={self.bob.pk}&next={url}"
        )
        self.assertEqual(response.context["form"]["user"].value(), str(self.bob.pk))
        response = self.client.post(
            f"/roles/{self.cook.pk}/assignments/?user={self.bob.pk}&next={url}",
            {"user": self.bob.pk},
        )
        self.assertRedirects(response, url)
        self.assertTrue(
            Assignment.objects.filter(role=self.cook, user=self.bob).exists()
        )
