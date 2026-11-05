import datetime as dt

from django.test import TestCase

from governance.accounts.models import User
from governance.roles.models import Accountability, Domain, Policy, Role


class SearchTest(TestCase):
    def test_search(self):
        self.client.force_login(User.objects.create_user("ada@example.com"))
        circle = Role.objects.create(
            name="Küche", is_circle=True, purpose="Essen für alle"
        )
        cook = Role.objects.create(name="Cook", circle=circle)
        Accountability.objects.create(
            role=cook, text="Registering domains for customers"
        )
        Domain.objects.create(role=cook, text="The stove")
        Policy.objects.create(
            role=circle,
            title="Stove",
            body=f"**Off** at night, ask @[Kok](role:{cook.pk})",
        )
        Role.objects.create(
            name="Old cook", circle=circle, archived_on=dt.date(2026, 1, 1)
        )

        response = self.client.get("/search/", {"q": "domains registering"})
        self.assertContains(response, "Registering domains for customers")
        # No space before the colon
        self.assertContains(response, "Search: domains registering")
        response = self.client.get("/search/", {"q": "kuche"})  # Ignores accents
        self.assertContains(response, circle.get_absolute_url())
        response = self.client.get("/search/", {"q": "stove"})
        self.assertContains(response, "The stove")
        self.assertContains(response, "Off at night, ask @Cook")  # Plain text
        response = self.client.get("/search/", {"q": "cook"})
        self.assertNotContains(response, "Old cook")
        self.assertContains(
            self.client.get("/search/", {"q": "nothing"}), "Nothing found"
        )
        self.assertNotContains(self.client.get("/search/"), "Nothing found")
