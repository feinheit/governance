import datetime as dt

from django.db import IntegrityError
from django.test import TestCase

from governance.accounts.models import User
from governance.roles.constitution import constitutional_texts
from governance.roles.models import Assignment, Role


class RolesTest(TestCase):
    def test_core_roles(self):
        anchor = Role.objects.create(name="Example Ltd", is_circle=True, purpose="Tea")
        anchor.create_core_roles()
        self.assertEqual(
            list(anchor.roles.values_list("core_role", flat=True)),
            ["lead", "facilitator", "secretary"],
        )
        circle = Role.objects.create(name="Kitchen", is_circle=True, circle=anchor)
        circle.create_core_roles()
        circle.create_core_roles()  # Idempotent
        self.assertEqual(circle.roles.count(), 4)

        lead = anchor.roles.get(core_role="lead")
        self.assertEqual(lead.display_purpose, "Tea")
        self.assertFalse(lead.is_elected)
        secretary = anchor.roles.get(core_role="secretary")
        self.assertIn("records", secretary.display_purpose)
        self.assertTrue(secretary.is_elected)

        with self.assertRaises(IntegrityError):
            Role.objects.create(circle=anchor, core_role="lead", name="Lead")

    def test_ancestors_and_settings(self):
        anchor = Role.objects.create(name="Example Ltd", is_circle=True)
        circle = Role.objects.create(name="Kitchen", is_circle=True, circle=anchor)
        role = Role.objects.create(name="Cook", circle=circle, purpose="Food")
        self.assertEqual(role.ancestors(), [anchor, circle])
        self.assertEqual(role.display_purpose, "Food")
        self.assertEqual(str(role), "Cook")

        self.assertEqual(role.effective_async_acceptance_days(), 4)
        anchor.async_acceptance_days = 3
        anchor.save()
        self.assertEqual(
            Role.objects.get(pk=role.pk).effective_async_acceptance_days(), 3
        )
        circle.async_acceptance_days = 1
        circle.save()
        self.assertEqual(
            Role.objects.get(pk=role.pk).effective_async_acceptance_days(), 1
        )
        self.assertEqual(
            Role.objects.get(pk=circle.pk).effective_async_acceptance_days(), 1
        )

        self.assertEqual(set(Role.objects.circles()), {anchor, circle})
        role.archived_on = dt.date(2026, 1, 1)
        role.save()
        self.assertNotIn(role, Role.objects.active())

    def test_current_assignments(self):
        role = Role.objects.create(name="Cook")
        user = User.objects.create_user("ada@example.com")
        assignment = Assignment.objects.create(
            role=role,
            user=user,
            starts_on=dt.date(2026, 1, 1),
            ends_on=dt.date(2026, 2, 1),
        )
        current = Assignment.objects.current
        self.assertEqual(list(current(on=dt.date(2026, 1, 1))), [assignment])
        self.assertEqual(list(current(on=dt.date(2026, 2, 1))), [])
        self.assertEqual(list(current(on=dt.date(2025, 12, 31))), [])
        self.assertEqual(str(assignment), "ada@example.com – Cook")

    def test_constitutional_texts(self):
        texts = constitutional_texts()
        self.assertIn("All governance records of the Circle", texts)
        self.assertIn("Facilitating the Circle’s Governance Process", texts)


class DepthFirstTest(TestCase):
    def test_depth_first(self):
        anchor = Role.objects.create(name="Example Ltd", is_circle=True)
        b = Role.objects.create(name="B", is_circle=True, circle=anchor)
        a = Role.objects.create(name="A", is_circle=True, circle=anchor)
        b1 = Role.objects.create(name="B1", is_circle=True, circle=b)
        a1 = Role.objects.create(name="A1", is_circle=True, circle=a)
        Role.objects.create(
            name="Gone", is_circle=True, circle=a, archived_on=dt.date(2026, 1, 1)
        )
        Role.objects.create(name="Not a circle", circle=a)
        circles = Role.objects.depth_first()
        self.assertEqual(circles, [anchor, a, a1, b, b1])
        self.assertEqual([c.depth for c in circles], [0, 1, 2, 1, 2])

    def test_person_page_order(self):
        user = User.objects.create_user("ada@example.com")
        anchor = Role.objects.create(name="Example Ltd", is_circle=True)
        zoo = Role.objects.create(name="Zoo", is_circle=True, circle=anchor, position=1)
        kitchen = Role.objects.create(
            name="Kitchen", is_circle=True, circle=anchor, position=2
        )
        for circle, name in [(kitchen, "Cook"), (zoo, "Keeper"), (anchor, "Host")]:
            Assignment.objects.create(
                role=Role.objects.create(name=name, circle=circle), user=user
            )
        self.client.force_login(user)
        content = self.client.get(user.get_absolute_url()).content.decode()
        self.assertLess(content.index("Host"), content.index("Keeper"))
        self.assertLess(content.index("Keeper"), content.index("Cook"))


class FrequencyTest(TestCase):
    def test_by_frequency(self):
        from governance.roles.models import ChecklistItem, Metric, by_frequency

        role = Role.objects.create(name="Cook")
        yearly = ChecklistItem.objects.create(
            role=role, description="Oven", frequency="yearly"
        )
        weekly = ChecklistItem.objects.create(
            role=role, description="Fridge", frequency="weekly"
        )
        other = ChecklistItem.objects.create(role=role, description="Knives")
        metric = Metric.objects.create(
            role=role, description="Meals", frequency="weekly"
        )
        groups = by_frequency([yearly, weekly, other, metric])
        self.assertEqual(
            [(str(label), items) for label, items in groups],
            [
                ("weekly", [weekly, metric]),
                ("yearly", [yearly]),
                ("without frequency", [other]),
            ],
        )
        user = User.objects.create_user("ada@example.com")
        self.client.force_login(user)
        content = self.client.get(role.get_absolute_url()).content.decode()
        self.assertLess(content.index("Fridge"), content.index("Oven"))
        self.assertLess(content.index("Oven"), content.index("Knives"))

        # Circle pages show the items of their roles too, with the role
        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        role.circle = kitchen
        role.save()
        ChecklistItem.objects.create(
            role=kitchen, description="Menu planned", frequency="weekly"
        )
        content = self.client.get(kitchen.get_absolute_url()).content.decode()
        self.assertIn("Menu planned", content)
        self.assertIn("Fridge", content)
        # The role's name links to it
        self.assertIn(f'href="{role.get_absolute_url()}"\n        >Cook</a>', content)
