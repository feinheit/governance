import datetime as dt

from django.test import TestCase

from governance.accounts.models import User
from governance.roles.models import (
    Accountability,
    Assignment,
    Domain,
    Link,
    Policy,
    Role,
)


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
        self.assertContains(response, "badge wb-tone-circle")  # Circles are marked
        response = self.client.get("/search/", {"q": "stove"})
        self.assertContains(response, "The stove")
        self.assertContains(response, "Off at night, ask @Cook")  # Plain text
        response = self.client.get("/search/", {"q": "cook"})
        self.assertNotContains(response, "Old cook")
        self.assertContains(
            self.client.get("/search/", {"q": "nothing"}), "Nothing found"
        )
        self.assertNotContains(self.client.get("/search/"), "Nothing found")

    def test_links(self):
        """By title and description (keywords), leading to the page and to
        the role keeping it; not those of archived roles"""
        self.client.force_login(User.objects.create_user("ada@example.com"))
        circle = Role.objects.create(name="Kitchen", is_circle=True)
        cook = Role.objects.create(name="Cook", circle=circle)
        Link.objects.create(
            role=cook,
            title="Cooking and eating",
            url="https://handbook.example.com/cooking/",
            description="Kitchen duty, hours, groceries",
        )
        old = Role.objects.create(
            name="Old cook", circle=circle, archived_on=dt.date(2026, 1, 1)
        )
        Link.objects.create(
            role=old, title="Old recipes", url="https://example.com/recipes/"
        )

        response = self.client.get("/search/", {"q": "hours kitchen"})
        self.assertContains(response, '<h2 class="h6 mb-0">Links</h2>', html=True)
        self.assertContains(response, 'href="https://handbook.example.com/cooking/"')
        self.assertContains(response, "Kitchen duty, hours, groceries")
        self.assertContains(response, cook.get_absolute_url())
        response = self.client.get("/search/", {"q": "recipes"})
        self.assertContains(response, "Nothing found")

    def test_what_the_pages_show(self):
        """Mentions with the current names, not their markup; the core
        roles' constitutional texts"""
        self.client.force_login(User.objects.create_user("ada@example.com"))
        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        kitchen.create_core_roles()
        cook = Role.objects.create(name="Cook", circle=kitchen)
        pastry = Role.objects.create(name="Pastry", circle=kitchen)
        Accountability.objects.create(
            role=cook, text=f"Asking @[Baker](role:{pastry.pk})"
        )
        response = self.client.get("/search/", {"q": "asking pastry"})
        self.assertContains(response, cook.get_absolute_url())
        self.assertContains(
            self.client.get("/search/", {"q": "(role:"}), "Nothing found"
        )
        secretary = kitchen.roles.get(core_role="secretary")
        response = self.client.get("/search/", {"q": "governance records"})
        self.assertContains(response, secretary.get_absolute_url())

    def test_people(self):
        """Active people by name, short name and mail address, first, with
        their circles"""
        self.client.force_login(User.objects.create_user("ada@example.com"))
        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        cook = Role.objects.create(name="Cook", circle=kitchen)
        zoe = User.objects.create_user(
            "zoe@example.com", full_name="Zoë Cook", short_name="Zo"
        )
        Assignment.objects.create(role=cook, user=zoe)
        User.objects.create_user(
            "old@example.com", full_name="Old Cook", is_active=False
        )

        response = self.client.get("/search/", {"q": "zoe COOK"})
        self.assertEqual(response.context["results"]["people"], [zoe])
        self.assertContains(response, '<h2 class="h6 mb-0">People</h2>', html=True)
        self.assertContains(response, zoe.get_absolute_url())
        self.assertContains(response, "Kitchen")  # Her circle
        self.assertNotContains(response, "Nothing found")
        self.assertEqual(
            self.client.get("/search/", {"q": "zo"}).context["results"]["people"],
            [zoe],
        )
        # Also by mail address
        self.assertEqual(
            self.client.get("/search/", {"q": "zoe@example"}).context["results"][
                "people"
            ],
            [zoe],
        )
        # People first, inactive ones not at all
        response = self.client.get("/search/", {"q": "cook"})
        self.assertEqual(response.context["results"]["people"], [zoe])
        content = response.content.decode()
        self.assertLess(
            content.index(zoe.get_absolute_url()),
            content.index(cook.get_absolute_url()),
        )
