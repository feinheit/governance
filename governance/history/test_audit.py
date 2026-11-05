import datetime as dt

from django.db import connection
from django.test import TestCase
from django.utils import timezone

from governance.accounts.models import User
from governance.history.audit import (
    canonical,
    rows_on,
    structure_from_database,
    structure_on,
)
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
            canonical(structure_on(today)), canonical(structure_from_database(today))
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
        final = structure_from_database(day3)
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


class BusyDayTest(AuditTestCase):
    def test_changes_undone_the_same_day(self):
        """Several proposals on one day: the history shows what the day
        changed, not the steps undone the same day"""
        from governance.history.backfill import backfill
        from governance.history.models import Change
        from governance.proposals.instructions import adopt
        from governance.proposals.models import Proposal

        ada = User.objects.create_user("ada@example.com")
        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        kitchen.create_core_roles()
        cook = Role.objects.create(name="Cook", circle=kitchen)
        waiter = Role.objects.create(name="Waiter", circle=kitchen)
        dishwasher = Role.objects.create(name="Dishwasher", circle=kitchen)
        bakery = Role.objects.create(name="Bakery", circle=kitchen, is_circle=True)
        bakery.create_core_roles()
        Role.objects.create(name="Baker", circle=bakery)
        Assignment.objects.create(role=cook, user=ada)
        today = timezone.localdate()
        yesterday = today - dt.timedelta(days=1)
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM audit_logged_actions")
        backfill([(yesterday, structure_from_database(yesterday))])

        def governance(*instructions):
            return adopt(
                Proposal.objects.create(
                    circle=kitchen,
                    proposer=ada,
                    tension="Busy",
                    created_at=timezone.now(),
                    instructions=list(instructions),
                )
            )

        def rename(role, old, new):
            governance({
                "op": "replace",
                "path": f"/roles/{role.pk}/name",
                "original_value": old,
                "value": new,
            })

        rename(cook, "Cook", "Chef")
        rename(cook, "Chef", "Cook")
        governance({
            "op": "move",
            "path": f"/roles/{bakery.pk}/supporting_circle/roles/{waiter.pk}",
            "from": f"/roles/{waiter.pk}",
        })
        governance({
            "op": "move",
            "path": f"/roles/{waiter.pk}",
            "from": f"/circles/{bakery.pk}/roles/{waiter.pk}",
        })
        governance(
            {"op": "add", "path": "/roles/n1"},
            {"op": "add", "path": "/roles/n1/name", "value": "Temp"},
        )
        temp = Role.objects.get(name="Temp")
        governance({"op": "remove", "path": f"/roles/{temp.pk}"})
        governance({"op": "add", "path": f"/roles/{dishwasher.pk}/supporting_circle"})
        governance({
            "op": "remove",
            "path": f"/roles/{dishwasher.pk}/supporting_circle",
        })
        rename(dishwasher, "Dishwasher", "Washer")  # The day's only change

        self.assertEqual(
            canonical(structure_on(today)), canonical(structure_from_database(today))
        )
        self.assertEqual(
            [
                (change.role, change.kind, change.old, change.new)
                for change in Change.objects.filter(date=today)
            ],
            [(dishwasher, "name", "Dishwasher", "Washer")],
        )


class ChangesRightAwayTest(AuditTestCase):
    def test_outside_proposals(self):
        """Assignments, domain policies, elections and deactivations show in
        the history right away, not only after the nightly job"""
        from django.urls import reverse

        from governance.history.backfill import backfill
        from governance.history.models import Change
        from governance.meetings.elections import record_election
        from governance.meetings.models import Meeting

        root = User.objects.create_superuser("root@example.com", full_name="Root")
        eve = User.objects.create_user("eve@example.com", full_name="Eve")
        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        kitchen.create_core_roles()
        cook = Role.objects.create(name="Cook", circle=kitchen)
        fridge = Domain.objects.create(role=cook, text="The fridge")
        today = timezone.localdate()
        yesterday = today - dt.timedelta(days=1)
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM audit_logged_actions")
        backfill([(yesterday, structure_from_database(yesterday))])

        def kinds():
            return {
                (change.policy or change.role, change.kind)
                for change in Change.objects.filter(date=today)
            }

        self.client.force_login(root)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(f"/roles/{cook.pk}/assignments/", {"user": eve.pk})
        self.assertIn((cook, "assigned"), kinds())

        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                f"/roles/{cook.pk}/domain-policies/new/",
                {"title": "Labels", "body": "Always", "domain": fridge.pk},
            )
        self.assertIn((Policy.objects.get(title="Labels"), "policy-added"), kinds())

        facilitator = kitchen.roles.get(core_role="facilitator")
        meeting = Meeting.objects.create(
            circle=kitchen, kind=Meeting.GOVERNANCE, started_at=timezone.now()
        )
        with self.captureOnCommitCallbacks(execute=True):
            record_election(meeting, facilitator, eve, today + dt.timedelta(days=365))
        self.assertIn((facilitator, "assigned"), kinds())

        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                reverse("admin:accounts_user_change", args=[eve.pk]),
                {"email": eve.email, "full_name": eve.full_name},
            )
        eve.refresh_from_db()
        self.assertFalse(eve.is_active)
        # Assigned and unassigned the same day: neither shows
        self.assertNotIn((cook, "assigned"), kinds())
        self.assertNotIn((facilitator, "assigned"), kinds())
