import datetime as dt

from django.db import connection
from django.test import TestCase
from django.utils import timezone

from governance.accounts.models import User
from governance.history.audit import rows_on, structure_on
from governance.history.snapshots import build_snapshot, canonical
from governance.roles.models import Accountability, Assignment, Domain, Policy, Role


class AuditTestCase(TestCase):
    """Without the audit rows other tests committed (e.g. the end-to-end
    tests): the audit table isn't flushed between tests"""

    def setUp(self):
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM audit_logged_actions")


class StructureOnTest(AuditTestCase):
    def test_like_the_snapshot(self):
        """The structure from the audit log is the snapshot's"""
        ada = User.objects.create_user("ada@example.com")
        kitchen = Role.objects.create(name="Kitchen", is_circle=True, purpose="Food")
        kitchen.create_core_roles()
        cook = Role.objects.create(name="Cook", circle=kitchen, purpose="Soup")
        Accountability.objects.create(role=cook, text="Cooking", position=1)
        Accountability.objects.create(role=cook, text="Tasting", position=0)
        fridge = Domain.objects.create(role=cook, text="The fridge")
        Assignment.objects.create(role=cook, user=ada, focus="Soup")
        Policy.objects.create(role=kitchen, title="Clean up", body="Always")
        Policy.objects.create(role=cook, title="Labels", domain=fridge)
        old = Role.objects.create(name="Old", circle=kitchen)
        # Changes and removals since
        cook.strategy = "Fresh first"
        cook.save()
        Accountability.objects.filter(text="Tasting").delete()
        old.archived_on = timezone.localdate()
        old.save()

        today = timezone.localdate()
        self.assertEqual(
            canonical(structure_on(today)), canonical(build_snapshot(today))
        )
        self.assertEqual(
            structure_on(today)["roles"][str(cook.pk)]["strategy"], "Fresh first"
        )
        self.assertEqual(
            structure_on(today - dt.timedelta(days=1)), {"roles": {}, "policies": {}}
        )


class BackfillTest(AuditTestCase):
    def test_backfill(self):
        """The history before the app as audit rows: every day's structure
        comes back from the audit log"""
        import copy

        from governance.history.backfill import backfill

        kitchen = Role.objects.create(name="Kitchen", is_circle=True, purpose="Food")
        kitchen.create_core_roles()
        cook = Role.objects.create(name="Cook", circle=kitchen, purpose="Soup")
        cooking = Accountability.objects.create(role=cook, text="Cooking")
        policy = Policy.objects.create(role=kitchen, title="Clean up", body="Always")
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM audit_logged_actions")  # The import's rows

        day3 = dt.date(2026, 3, 1)
        final = build_snapshot(day3)
        day1, day2 = dt.date(2026, 1, 1), dt.date(2026, 2, 1)
        first = copy.deepcopy(final)
        first["roles"][str(cook.pk)] |= {
            "name": "Cook's helper",
            "accountabilities": ["Cooking", None],  # A text not recorded
        }
        first["roles"]["999999"] = first["roles"][str(cook.pk)] | {"name": "Gone"}
        first["policies"][str(policy.pk)]["title"] = "Tidying"
        second = copy.deepcopy(final)
        second["roles"][str(cook.pk)]["accountabilities"] = ["Boiling"]

        backfill([(day1, first), (day2, second), (day3, final)])

        for day, data in [(day1, first), (day2, second), (day3, final)]:
            with self.subTest(day=day):
                self.assertEqual(canonical(structure_on(day)), canonical(data))
        self.assertEqual(
            structure_on(dt.date(2025, 12, 31)), {"roles": {}, "policies": {}}
        )
        # The accountability at the end is the real row
        rows = rows_on(day3)["accountabilities"]
        self.assertEqual(rows[cooking.pk]["text"], "Cooking")
