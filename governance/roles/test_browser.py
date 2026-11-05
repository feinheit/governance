from django.test import TestCase

from governance.accounts.models import User
from governance.roles.browser import circle_tree
from governance.roles.models import Assignment, Role


class CircleBrowserTest(TestCase):
    def test_tree_and_page(self):
        ada = User.objects.create_user("ada@example.com", full_name="Ada")
        self.client.force_login(ada)
        self.assertContains(self.client.get("/circles/"), "No circles yet.")

        anchor = Role.objects.create(name="Example Ltd", is_circle=True)
        anchor.create_core_roles()
        kitchen = Role.objects.create(name="Kitchen", is_circle=True, circle=anchor)
        cook = Role.objects.create(name="Cook", circle=kitchen)
        Role.objects.create(name="Gone", circle=kitchen, archived_on="2026-01-01")
        Assignment.objects.create(role=cook, user=ada)

        tree = circle_tree(ada)
        self.assertEqual((tree["name"], tree["kind"]), ("Example Ltd", "circle"))
        self.assertEqual(
            {(child["name"], child["kind"]) for child in tree["children"]},
            {
                ("Circle Lead", "core"),
                ("Facilitator", "core"),
                ("Secretary", "core"),
                ("Kitchen", "circle"),
            },
        )
        kitchen_node = next(c for c in tree["children"] if c["name"] == "Kitchen")
        self.assertEqual(
            kitchen_node["children"],
            [
                {
                    "id": cook.pk,
                    "name": "Cook",
                    "url": f"/roles/{cook.pk}/",
                    "kind": "role",
                    "holders": ["Ada"],
                    "elected": False,
                    "lead": False,
                    "mine": True,
                }
            ],
        )

        response = self.client.get("/circles/")
        # The list works without JavaScript, the island gets the data
        self.assertContains(response, f'href="/roles/{cook.pk}/"')
        self.assertContains(response, 'id="circle-tree"')
        self.assertNotContains(response, "Gone")
        self.assertContains(response, "your role")
        secretary = next(c for c in tree["children"] if c["name"] == "Secretary")
        self.assertEqual((secretary["elected"], secretary["mine"]), (True, False))
