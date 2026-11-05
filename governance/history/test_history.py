import datetime as dt

from django.test import TestCase

from governance.history.changes import diff_policies, diff_roles
from governance.history.models import Change, Snapshot
from governance.history.update import update_changes
from governance.roles.models import Policy, Role


def role(name, *, circle=None, accountabilities=(), assignments=(), **kwargs):
    return {
        "name": name,
        "purpose": kwargs.get("purpose", ""),
        "strategy": "",
        "circle": circle,
        "is_circle": kwargs.get("is_circle", False),
        "core_role": "",
        "short_name": "",
        "accountabilities": list(accountabilities),
        "domains": [],
        "assignments": [{"user": user, "elected_until": None} for user in assignments],
    }


class HistoryTest(TestCase):
    def test_diff(self):
        old = {
            "roles": {
                "1": role("Kok", accountabilities=["Cooking", None], assignments=[7]),
                "2": role("Dishwasher"),
            },
            "policies": {"5": {"title": "Tea", "body": "Always", "role": 1}},
        }
        new = {
            "roles": {
                "1": role(
                    "Cook",
                    circle=9,
                    accountabilities=["Cooking", "Baking"],
                    assignments=[8],
                    is_circle=True,
                    purpose="Food",
                ),
                "3": role("Waiter"),
            },
            "policies": {"6": {"title": "Fridge", "body": "", "role": 1}},
        }
        self.assertEqual(
            sorted(diff_roles(old, new), key=str),
            sorted(
                [
                    (3, "added", "", "Waiter"),
                    (2, "removed", "Dishwasher", ""),
                    (1, "name", "Kok", "Cook"),
                    (1, "purpose", "", "Food"),
                    (1, "moved", None, 9),
                    (1, "circle", "", ""),
                    (1, "accountabilities-added", "", "Baking"),
                    (1, "accountabilities-unrecorded", 1, 0),
                    (1, "assigned", "", 8),
                    (1, "unassigned", 7, ""),
                ],
                key=str,
            ),
        )
        self.assertEqual(
            sorted(diff_policies(old, new)),
            [(5, 1, "removed", "Tea", ""), (6, 1, "added", "", "Fridge")],
        )
        changed = {"policies": {"5": {"title": "Tea!", "body": "Often", "role": 2}}}
        self.assertEqual(
            sorted(diff_policies(old, changed)),
            [
                (5, 2, "body", "Always", "Often"),
                (5, 2, "moved", 1, 2),
                (5, 2, "title", "Tea", "Tea!"),
            ],
        )

    def test_update_changes(self):
        cook = Role.objects.create(name="Cook")
        policy = Policy.objects.create(role=cook, title="Tea")
        day = dt.date(2026, 1, 1)
        Snapshot.objects.create(date=day, data={"roles": {}, "policies": {}})
        Snapshot.objects.create(
            date=day + dt.timedelta(days=1),
            data={
                "roles": {str(cook.pk): role("Cook")},
                "policies": {
                    str(policy.pk): {"title": "Tea", "body": "", "role": cook.pk}
                },
            },
        )
        Snapshot.objects.create(
            date=day + dt.timedelta(days=2),
            data={"roles": {str(cook.pk): role("Chef")}, "policies": {}},
        )
        self.assertEqual(update_changes(), 4)
        self.assertEqual(
            list(
                Change.objects.order_by("date", "kind").values_list(
                    "kind", "role", "policy"
                )
            ),
            [
                ("added", cook.pk, None),
                ("policy-added", cook.pk, policy.pk),
                ("name", cook.pk, None),
                ("policy-removed", cook.pk, policy.pk),
            ],
        )
        self.assertEqual(update_changes(since=day + dt.timedelta(days=2)), 2)
        self.assertEqual(Change.objects.count(), 4)
        self.assertEqual(
            str(Snapshot.objects.on(day + dt.timedelta(days=5))), "2026-01-03"
        )


class HistoryViewsTest(TestCase):
    def test_views(self):
        from django.utils import timezone

        from governance.accounts.models import User
        from governance.proposals.models import Proposal

        user = User.objects.create_user("ada@example.com", full_name="Ada")
        self.client.force_login(user)
        circle = Role.objects.create(name="Kitchen", is_circle=True)
        cook = Role.objects.create(name="Cook", circle=circle)
        policy = Policy.objects.create(role=circle, title="Tea")
        day = dt.date(2026, 1, 1)
        base = {
            str(circle.pk): role("Kitchen", is_circle=True),
            str(cook.pk): role(
                "Kok",
                circle=circle.pk,
                accountabilities=["Frying", None],
                assignments=[user.pk],
            ),
        }
        Snapshot.objects.create(date=day, data={"roles": base, "policies": {}})
        Snapshot.objects.create(
            date=day + dt.timedelta(days=1),
            data={
                "roles": base
                | {str(cook.pk): role("Cook", circle=circle.pk, purpose="Food")},
                "policies": {
                    str(policy.pk): {
                        "title": "Tea",
                        "body": "Always",
                        "role": circle.pk,
                    }
                },
            },
        )
        update_changes()
        proposal = Proposal.objects.create(
            circle=circle,
            tension="Better names",
            status=Proposal.ADOPTED,
            created_at=timezone.now(),
            decided_at=timezone.make_aware(dt.datetime(2026, 1, 2, 10)),
        )
        proposal.roles.add(cook)

        response = self.client.get(f"/roles/{cook.pk}/history/")
        self.assertContains(response, "Better names")
        self.assertContains(response, "Renamed")
        self.assertContains(response, "Purpose changed")
        self.assertNotContains(response, "No longer assigned")
        self.assertContains(
            self.client.get(f"/roles/{cook.pk}/history/?assignments=1"),
            "No longer assigned",
        )

        response = self.client.get("/history/")
        self.assertContains(response, "Policy added")
        self.assertContains(response, "Better names")
        self.assertEqual(self.client.get("/history/?page=2").status_code, 200)

        response = self.client.get(f"/roles/{cook.pk}/as-of/?date=2026-01-01")
        self.assertContains(response, "Kok")
        self.assertContains(response, "Frying")
        self.assertContains(response, "1 accountability (text not recorded)")
        self.assertContains(response, "Ada")
        response = self.client.get(f"/roles/{circle.pk}/as-of/?date=2026-01-05")
        self.assertContains(response, "Cook")
        self.assertContains(response, "Always")
        self.assertEqual(
            self.client.get(f"/roles/{cook.pk}/as-of/?date=2025-01-01").status_code, 404
        )
        self.assertEqual(
            self.client.get(f"/roles/{cook.pk}/as-of/?date=nonsense").status_code, 200
        )
        Snapshot.objects.update(data={"roles": {}, "policies": {}})
        self.assertContains(
            self.client.get(f"/roles/{cook.pk}/as-of/?date=2026-01-05"), "didn't exist"
        )


class SnapshotTaskTest(TestCase):
    def test_take_snapshot(self):
        from django.core.management import call_command
        from django.utils import timezone

        from governance.accounts.models import User
        from governance.history.snapshots import take_snapshot
        from governance.roles.models import Accountability, Assignment

        ada = User.objects.create_user("ada@example.com", full_name="Ada")
        circle = Role.objects.create(name="Kitchen", is_circle=True)
        circle.create_core_roles()
        cook = Role.objects.create(name="Cook", circle=circle)
        Accountability.objects.create(role=cook, text="Cooking")
        Assignment.objects.create(role=cook, user=ada, focus="Soup")
        Policy.objects.create(role=circle, title="Tea", body="Always")
        day = timezone.localdate() - dt.timedelta(days=5)

        data = take_snapshot(day).data
        entry = data["roles"][str(cook.pk)]
        self.assertEqual(
            (entry["name"], entry["circle"], entry["accountabilities"]),
            ("Cook", circle.pk, ["Cooking"]),
        )
        self.assertEqual(
            entry["assignments"], [{"user": ada.pk, "elected_until": None}]
        )
        secretary = circle.roles.get(core_role="secretary")
        # Constitutional texts like in GlassFrog's snapshots, in English
        self.assertIn(
            "Scheduling Governance Meetings for the Circle",
            data["roles"][str(secretary.pk)]["accountabilities"],
        )
        self.assertEqual(
            data["roles"][str(secretary.pk)]["domains"],
            ["All governance records of the Circle"],
        )
        self.assertEqual(len(data["policies"]), 1)

        # Nothing changed, no snapshot
        self.assertIsNone(take_snapshot(day + dt.timedelta(days=1)))
        self.assertEqual(Snapshot.objects.count(), 1)

        cook.name = "Chef"
        cook.save()
        Assignment.objects.update(ends_on=day + dt.timedelta(days=2))
        take_snapshot(day + dt.timedelta(days=2))
        self.assertEqual(
            sorted(Change.objects.filter(role=cook).values_list("kind", "old", "new")),
            [("name", "Cook", "Chef"), ("unassigned", ada.pk, "")],
        )

        # The same day again without the change: the snapshot goes away
        cook.name = "Cook"
        cook.save()
        Assignment.objects.update(ends_on=None)
        self.assertIsNone(take_snapshot(day + dt.timedelta(days=2)))
        self.assertEqual(Snapshot.objects.count(), 1)
        self.assertFalse(Change.objects.filter(role=cook).exists())

        call_command("fairy_tasks")
        self.assertEqual(Snapshot.objects.count(), 1)  # Still no changes
