from django.test import TestCase

from governance.accounts.models import User
from governance.roles.models import Assignment, ChecklistItem, Metric, Role


class EditingTest(TestCase):
    def setUp(self):
        self.ada = User.objects.create_user("ada@example.com", full_name="Ada")
        self.bob = User.objects.create_user("bob@example.com", full_name="Bob")
        self.eve = User.objects.create_user("eve@example.com", full_name="Eve")
        self.kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        self.kitchen.create_core_roles()
        self.cook = Role.objects.create(name="Cook", circle=self.kitchen)
        # Ada leads the kitchen, Bob is its Secretary, Eve cooks
        Assignment.objects.create(
            role=self.kitchen.roles.get(core_role="lead"), user=self.ada
        )
        Assignment.objects.create(
            role=self.kitchen.roles.get(core_role="secretary"), user=self.bob
        )
        Assignment.objects.create(role=self.cook, user=self.eve)

    def test_strategy(self):
        url = f"/roles/{self.kitchen.pk}/strategy/"
        for user in [self.ada, self.bob]:  # The Secretary stands in
            self.client.force_login(user)
            self.assertContains(self.client.get(f"/roles/{self.kitchen.pk}/"), url)
            self.client.post(url, {"strategy": f"Soup first, says {user}"})
            self.kitchen.refresh_from_db()
            self.assertEqual(self.kitchen.strategy, f"Soup first, says {user}")

        self.client.force_login(self.eve)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(
            self.client.get(f"/roles/{self.cook.pk}/strategy/").status_code, 403
        )  # Not a circle

    def test_metrics(self):
        self.client.force_login(self.ada)
        url = f"/roles/{self.cook.pk}/metrics/new/"
        self.assertContains(self.client.get(f"/roles/{self.cook.pk}/"), url)
        self.client.post(
            url,
            {
                "description": "Soups per week",
                "frequency": "weekly",
                "link": "https://example.com/",
            },
        )
        metric = Metric.objects.get()
        self.assertEqual((metric.role, metric.frequency), (self.cook, "weekly"))
        self.client.post(
            f"/items/metrics/{metric.pk}/",
            {"description": "Soups served", "frequency": "", "link": ""},
        )
        metric.refresh_from_db()
        self.assertEqual(metric.description, "Soups served")

        # The cook holds the role but doesn't edit its metrics
        self.client.force_login(self.eve)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(
            self.client.post(f"/items/metrics/{metric.pk}/delete/").status_code, 403
        )
        self.client.force_login(self.bob)
        self.client.post(f"/items/metrics/{metric.pk}/delete/")
        self.assertFalse(Metric.objects.exists())

    def test_checklist_items(self):
        """Anybody adds, edits and deletes them"""
        outsider = User.objects.create_user("zoe@example.com")
        self.client.force_login(outsider)
        self.client.post(
            f"/roles/{self.kitchen.pk}/checklist/new/",
            {"description": "Fridge cleaned", "frequency": "monthly", "link": ""},
        )
        item = ChecklistItem.objects.get()
        self.assertEqual(item.role, self.kitchen)
        self.assertContains(
            self.client.get(f"/roles/{self.kitchen.pk}/"), "Fridge cleaned"
        )
        self.client.post(f"/items/checklist/{item.pk}/delete/")
        self.assertFalse(ChecklistItem.objects.exists())
        self.assertEqual(
            self.client.get(f"/items/nonsense/{item.pk}/").status_code, 403
        )

    def test_links(self):
        """Links to external tools, anybody edits them"""
        from governance.roles.models import Link

        self.client.force_login(self.eve)
        url = f"/roles/{self.kitchen.pk}/links/new/"
        self.assertContains(self.client.get(f"/roles/{self.kitchen.pk}/"), url)
        response = self.client.post(
            url, {"title": "Tasks", "url": "javascript:alert(1)", "description": ""}
        )
        self.assertEqual(response.status_code, 200)  # Not a valid URL
        self.client.post(
            url,
            {
                "title": "Tasks",
                "url": "https://tasks.example.com/projects/2",
                "description": "Projects and to-dos",
            },
        )
        link = Link.objects.get()
        response = self.client.get(f"/roles/{self.kitchen.pk}/")
        self.assertContains(response, 'href="https://tasks.example.com/projects/2"')
        self.assertContains(response, "Projects and to-dos")
        self.client.post(f"/items/links/{link.pk}/delete/")
        self.assertFalse(Link.objects.exists())
