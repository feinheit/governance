from django.test import TestCase

from governance.accounts.models import User
from governance.roles.export import governance_data
from governance.roles.models import (
    Accountability,
    Assignment,
    Domain,
    Link,
    Metric,
    Policy,
    Role,
)


class ExportTest(TestCase):
    def test_markdown(self):
        user = User.objects.create_user("ada@example.com", full_name="Ada Example")
        self.client.force_login(user)
        anchor = Role.objects.create(
            name="Example Ltd", is_circle=True, purpose="Tea\\n\\nfor all"
        )
        anchor.create_core_roles()
        kitchen = Role.objects.create(
            name="Kitchen", is_circle=True, circle=anchor, strategy="Fresh first"
        )
        kitchen.create_core_roles()
        cook = Role.objects.create(name="Cook", circle=kitchen, purpose="Food")
        Accountability.objects.create(
            role=cook, text=f"Asking @[Old](role:{kitchen.pk})"
        )
        Policy.objects.create(role=anchor, title="Tea", body="Always")
        Policy.objects.create(role=cook, title="Stove", body="Off at night")
        Assignment.objects.create(role=cook, user=user, focus="Soups")

        # No button, the URL (and later the CLI) offers it
        response = self.client.get(anchor.get_absolute_url())
        self.assertNotContains(response, "/export/governance.md")
        response = self.client.get("/export/governance.md?people=1")
        self.assertEqual(response["Content-Type"], "text/markdown; charset=utf-8")
        text = response.content.decode()
        self.assertIn("## Example Ltd", text)
        self.assertIn("### Kitchen", text)
        self.assertIn("#### Cook", text)
        self.assertIn("Fresh first", text)
        self.assertIn("- Asking @Kitchen", text)  # Mentions with the current name
        self.assertIn("*Ada Example (Soups)*", text.replace("Role Leads: ", ""))
        # Unfilled: not the Circle Rep (5.1.1), a circle's Circle Lead the
        # super-circle's (1.4.2)
        self.assertIn("#### Circle Rep\n\n*Nobody*", text)
        self.assertIn(
            "#### Circle Lead\n\n*Held by the super-circle's Circle Leads*", text
        )
        self.assertIn("#### Facilitator\n\n*Held by the Circle Leads*", text)
        self.assertIn("Off at night", text)
        self.assertIn("- All governance records of the Circle", text)
        self.assertLess(text.index("## Example Ltd"), text.index("### Kitchen"))

        # Who holds the roles only when asked for: personal data
        text = self.client.get("/export/governance.md").content.decode()
        self.assertNotIn("Ada Example", text)

    def test_data(self):
        """The current state as a tree from the anchor circle down, each role
        with what belongs to it; mentions with the current names, the people
        when asked for"""
        user = User.objects.create_user("ada@example.com", full_name="Ada Example")
        anchor = Role.objects.create(name="Example Ltd", is_circle=True)
        anchor.create_core_roles()
        kitchen = Role.objects.create(name="Kitchen", is_circle=True, circle=anchor)
        cook = Role.objects.create(name="Cook", circle=kitchen, purpose="Food")
        Accountability.objects.create(
            role=cook, text=f"Asking @[Old](role:{kitchen.pk})"
        )
        stove = Domain.objects.create(role=cook, text="The stove")
        Policy.objects.create(role=cook, domain=stove, title="Off at night")
        Policy.objects.create(role=kitchen, title="Tea time", body="At four")
        Metric.objects.create(role=cook, description="Soups", frequency="Weekly")
        Link.objects.create(role=cook, title="Recipes", url="https://example.com/")
        Role.objects.create(name="Baker", circle=kitchen, archived_on="2026-01-01")
        Assignment.objects.create(role=cook, user=user, focus="Soups")

        data = governance_data()
        [company] = data["roles"]
        self.assertEqual(company["name"], "Example Ltd")
        names = [role["name"] for role in company["roles"]]
        self.assertIn("Kitchen", names)
        self.assertIn("Secretary", names)  # With the constitution's texts
        secretary = next(r for r in company["roles"] if r["name"] == "Secretary")
        self.assertEqual(secretary["domains"][0]["id"], None)
        [kitchen_entry] = [r for r in company["roles"] if r["name"] == "Kitchen"]
        self.assertEqual(kitchen_entry["policies"][0]["title"], "Tea time")
        [cook_entry] = kitchen_entry["roles"]  # Not the archived Baker
        self.assertEqual(cook_entry["accountabilities"][0]["text"], "Asking @Kitchen")
        self.assertEqual(
            cook_entry["domains"][0]["policies"][0]["title"], "Off at night"
        )
        self.assertEqual(cook_entry["policies"], [])
        self.assertEqual(cook_entry["metrics"][0]["frequency"], "Weekly")
        self.assertEqual(cook_entry["links"][0]["title"], "Recipes")
        self.assertNotIn("roles", cook_entry)
        self.assertNotIn("role_leads", cook_entry)
        self.assertNotIn("ada@example.com", str(data))

        [company] = governance_data(with_people=True)["roles"]
        [kitchen_entry] = [r for r in company["roles"] if r["name"] == "Kitchen"]
        self.assertEqual(
            kitchen_entry["roles"][0]["role_leads"][0]["email"], "ada@example.com"
        )
