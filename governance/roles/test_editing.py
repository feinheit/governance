import datetime as dt

from django.test import TestCase

from governance.accounts.models import User
from governance.roles.models import (
    Accountability,
    Assignment,
    ChecklistItem,
    Domain,
    Metric,
    Role,
)


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

    def test_strategy_mail(self):
        """A changed strategy goes to the members of the circle and of its
        sub-circles, where it applies too"""
        from django.core import mail

        pastry = Role.objects.create(name="Pastry", is_circle=True, circle=self.kitchen)
        zoe = User.objects.create_user("zoe@example.com", full_name="Zoe")
        Assignment.objects.create(
            role=Role.objects.create(name="Baker", circle=pastry), user=zoe
        )
        self.client.force_login(self.ada)
        url = f"/roles/{self.kitchen.pk}/strategy/"
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(url, {"strategy": "Soup first"})
        self.assertEqual(
            sorted(m.to[0] for m in mail.outbox),
            [
                "ada@example.com",
                "bob@example.com",
                "eve@example.com",
                "zoe@example.com",
            ],
        )
        self.assertEqual(mail.outbox[0].subject, "Strategy of Kitchen changed")
        self.assertIn("Soup first", mail.outbox[0].body)
        # Unchanged: no mail
        mail.outbox = []
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(url, {"strategy": "Soup first"})
        self.assertEqual(mail.outbox, [])
        # The previous one too
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(url, {"strategy": "Salad first"})
        self.assertIn("Salad first", mail.outbox[0].body)
        self.assertIn("Soup first", mail.outbox[0].body)

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
        # Asked first, e.g. in a modal
        self.assertContains(
            self.client.get(f"/items/metrics/{metric.pk}/delete/"),
            "Delete this metric?",
        )
        self.assertTrue(Metric.objects.exists())
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

    def test_reported_by(self):
        """The circle's page chooses who reports an item: the whole circle,
        one of its roles (a sub-circle in this circle's meetings) or the
        circle in its super-circle's"""
        anchor = Role.objects.create(name="Example Ltd", is_circle=True)
        anchor.create_core_roles()
        self.kitchen.circle = anchor
        self.kitchen.save()
        pastry = Role.objects.create(name="Pastry", is_circle=True, circle=self.kitchen)
        self.client.force_login(self.eve)
        url = f"/roles/{self.kitchen.pk}/checklist/new/"
        response = self.client.get(url)
        page = response.content.decode()
        # The circle's two first, then its roles
        self.assertLess(
            page.index("Kitchen (whole circle)"),
            page.index("Kitchen in Example Ltd"),
            page.index('<optgroup label="Roles">'),
        )
        self.assertLess(page.index('<optgroup label="Roles">'), page.index(">Cook<"))
        self.assertLess(page.index(">Cook<"), page.index("</optgroup>"))
        self.assertIn(">Pastry<", page)
        data = {"description": "Oven", "frequency": "", "link": ""}
        for reported_by, role, whole in [
            (f"{self.cook.pk}", self.cook, False),
            (f"{pastry.pk}", pastry, False),
            (f"{self.kitchen.pk}-up", self.kitchen, False),
            (f"{self.kitchen.pk}", self.kitchen, True),
        ]:
            self.client.post(url, data | {"reported_by": reported_by})
            item = ChecklistItem.objects.latest("pk")
            self.assertEqual((item.role, item.whole_circle), (role, whole))
            # Editing moves it
            self.client.post(
                f"/items/checklist/{item.pk}/?circle={self.kitchen.pk}",
                data | {"reported_by": f"{self.cook.pk}"},
            )
            item.refresh_from_db()
            self.assertEqual((item.role, item.whole_circle), (self.cook, False))
        self.assertEqual(
            self.client.post(url, data | {"reported_by": f"{anchor.pk}"}).status_code,
            200,
        )  # Not one of the circle's

        # Metrics: the Circle Leads of the circle reporting them; Ada leads
        # the kitchen, not the anchor circle
        self.client.force_login(self.ada)
        response = self.client.get(f"/roles/{self.kitchen.pk}/metrics/new/")
        self.assertContains(response, "Cook")
        self.assertNotContains(response, "Kitchen in Example Ltd")

    def test_checklists_and_metrics_cards(self):
        """Two cards like the two steps of the tactical meetings"""
        ChecklistItem.objects.create(role=self.kitchen, description="Fridge cleaned")
        Metric.objects.create(role=self.cook, description="Soups per week")
        self.client.force_login(self.eve)
        page = self.client.get(f"/roles/{self.kitchen.pk}/").content.decode()
        checklists = page.index(">Checklists</h2>")
        metrics = page.index(">Metrics</h2>")
        self.assertLess(checklists, page.index("Fridge cleaned"), metrics)
        self.assertLess(metrics, page.index("Soups per week"))
        self.assertNotIn("Checklists and metrics", page)

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

    def test_notes(self):
        """Notes in Markdown, anybody edits them, nobody gets a mail"""
        from django.core import mail

        from governance.roles.models import Note

        self.client.force_login(self.eve)
        url = f"/roles/{self.kitchen.pk}/notes/new/"
        self.assertContains(self.client.get(f"/roles/{self.kitchen.pk}/"), url)
        self.assertEqual(
            self.client.post(url, {"title": "", "body": ""}).status_code, 200
        )
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                url,
                {"title": "Ordering", "body": f"Ask **@[Cook](role:{self.cook.pk})**"},
            )
        note = Note.objects.get()
        response = self.client.get(f"/roles/{self.kitchen.pk}/")
        self.assertContains(response, f'id="note-{note.pk}"')
        self.assertContains(response, "<strong>")
        self.assertContains(response, self.cook.get_absolute_url())
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                f"/items/notes/{note.pk}/", {"title": "Orders", "body": "By mail"}
            )
        note.refresh_from_db()
        self.assertEqual((note.title, note.body), ("Orders", "By mail"))
        self.client.post(f"/items/notes/{note.pk}/delete/")
        self.assertFalse(Note.objects.exists())
        self.assertEqual(mail.outbox, [])
        # Archived roles keep theirs
        self.cook.archived_on = dt.date.today()
        self.cook.save()
        url = f"/roles/{self.cook.pk}/notes/new/"
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_texts_order(self):
        """Anybody orders a role's accountabilities and domains, by dragging
        (their IDs) or with the arrows; it isn't governance, archived roles
        keep theirs"""
        cooking, frying, tasting = (
            Accountability.objects.create(role=self.cook, text=text, position=i)
            for i, text in enumerate(["Cooking", "Frying", "Tasting"])
        )
        order = f"/roles/{self.cook.pk}/accountabilities/order/"

        def texts():
            return list(self.cook.accountabilities.values_list("text", flat=True))

        self.client.force_login(self.eve)  # Holds no role in the kitchen
        response = self.client.get(self.cook.get_absolute_url())
        self.assertContains(response, order)
        # Missing and unknown ones: the others keep their order after them
        response = self.client.post(order, {"ids": [tasting.pk, 999, cooking.pk]})
        self.assertRedirects(response, self.cook.get_absolute_url())
        self.assertEqual(texts(), ["Tasting", "Cooking", "Frying"])

        move = f"/roles/{self.cook.pk}/accountabilities/{frying.pk}/move/"
        self.client.post(move, {"direction": "up"})
        self.assertEqual(texts(), ["Tasting", "Frying", "Cooking"])
        self.client.post(
            move.replace(str(frying.pk), str(tasting.pk)), {"direction": "up"}
        )
        self.assertEqual(texts(), ["Tasting", "Frying", "Cooking"])
        self.assertEqual(self.client.get(order).status_code, 405)

        oven, pots = (
            Domain.objects.create(role=self.cook, text=text, position=i)
            for i, text in enumerate(["Oven", "Pots"])
        )
        domains = f"/roles/{self.cook.pk}/domains/order/"
        self.assertContains(self.client.get(self.cook.get_absolute_url()), domains)
        self.client.post(domains, {"ids": [pots.pk, oven.pk]})
        self.assertEqual(
            list(self.cook.domains.values_list("text", flat=True)), ["Pots", "Oven"]
        )
        self.assertEqual(
            self.client.post(f"/roles/{self.cook.pk}/policies/order/").status_code,
            404,
        )

        Role.objects.filter(pk=self.cook.pk).update(archived_on=dt.date(2026, 1, 1))
        self.assertEqual(
            self.client.post(order, {"ids": [cooking.pk]}).status_code, 404
        )
        self.assertEqual(texts(), ["Tasting", "Frying", "Cooking"])

    def test_links_and_notes_order(self):
        """Links and notes are one list in one card, anybody orders them;
        new ones come last"""
        from governance.roles.models import Link, Note

        self.client.force_login(self.eve)
        url = f"/roles/{self.cook.pk}/"
        self.client.post(
            f"{url}links/new/",
            {"title": "Board", "url": "https://example.com/", "description": ""},
        )
        self.client.post(f"{url}notes/new/", {"title": "Pots", "body": ""})
        self.client.post(
            f"{url}links/new/",
            {"title": "Recipes", "url": "https://example.com/r", "description": ""},
        )
        board, recipes = Link.objects.order_by("pk")
        pots = Note.objects.get()

        def titles():
            response = self.client.get(url)
            content = response.content.decode()
            return sorted(["Board", "Pots", "Recipes"], key=content.index)

        response = self.client.get(url)
        self.assertContains(response, "Links and notes")
        self.assertEqual(titles(), ["Board", "Pots", "Recipes"])
        order = f"{url}references/order/"
        self.assertContains(response, order)
        self.assertContains(response, f'data-sortable-item="note-{pots.pk}"')
        self.client.post(order, {"ids": [f"link-{recipes.pk}", f"link-{board.pk}"]})
        self.assertEqual(titles(), ["Recipes", "Board", "Pots"])
        self.client.post(f"{url}references/note-{pots.pk}/move/", {"direction": "up"})
        self.assertEqual(titles(), ["Recipes", "Pots", "Board"])
