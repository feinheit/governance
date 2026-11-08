from django.test import TestCase

from governance.accounts.models import User
from governance.roles.models import Accountability, Assignment, Policy, Role


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
        self.assertIn("*Ada Example (Soups)*", text.replace("Held by: ", ""))
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
