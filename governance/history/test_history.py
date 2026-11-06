import datetime as dt

from django.test import TestCase

from governance.history.changes import diff_policies, diff_roles
from governance.history.models import Change
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


class ReelectedTest(TestCase):
    def test_reelected(self):
        """Electing the person holding the role for a new term is a change of
        its own, electing somebody else is an assignment"""
        import time_machine
        from django.utils import timezone

        from governance.accounts.models import User
        from governance.history.audit import structure_from_database
        from governance.meetings.elections import record_election
        from governance.meetings.models import Meeting

        ada = User.objects.create_user("ada@example.com", full_name="Ada")
        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        kitchen.create_core_roles()
        secretary = kitchen.roles.get(core_role="secretary")
        start = dt.date(2026, 1, 1)
        history((start, structure_from_database(start)))

        def elect(day, term):
            with time_machine.travel(dt.datetime(*day, 12), tick=False):
                meeting = Meeting.objects.create(
                    circle=kitchen, kind=Meeting.GOVERNANCE, started_at=timezone.now()
                )
                record_election(meeting, secretary, ada, term)
                meeting.ended_at = timezone.now()
                meeting.save(update_fields=["ended_at"])

        elect((2026, 1, 5), dt.date(2026, 12, 31))
        elect((2026, 12, 20), dt.date(2027, 12, 31))
        with time_machine.travel(dt.datetime(2026, 12, 21, 12), tick=False):
            update_changes()
        self.assertEqual(
            list(
                Change.objects
                .filter(role=secretary, kind__in=["assigned", "reelected"])
                .order_by("date")
                .values_list("date", "kind", "old", "new")
            ),
            [
                (dt.date(2026, 1, 5), "assigned", "", ada.pk),
                (dt.date(2026, 12, 20), "reelected", ada.pk, "2027-12-31"),
            ],
        )
        # Recorded after midnight (Zurich) in a meeting started before it:
        # the day it was recorded, like the assignments, also for the update
        # of today right after recording it
        with time_machine.travel(
            dt.datetime(2027, 12, 1, 22, 30, tzinfo=dt.UTC), tick=False
        ):
            meeting = Meeting.objects.create(
                circle=kitchen, kind=Meeting.GOVERNANCE, started_at=timezone.now()
            )
        with (
            time_machine.travel(
                dt.datetime(2027, 12, 1, 23, 30, tzinfo=dt.UTC), tick=False
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            record_election(meeting, secretary, ada, dt.date(2028, 12, 31))
        self.assertTrue(
            Change.objects.filter(
                role=secretary, kind="reelected", date=dt.date(2027, 12, 2)
            ).exists()
        )

        self.client.force_login(ada)
        response = self.client.get(f"/roles/{secretary.pk}/history/?assignments=1")
        self.assertContains(response, "Re-elected")
        self.assertContains(response, "until 31 December 2027")


class FollowingTest(TestCase):
    def test_circles_role_follows_its_core_roles(self):
        """A circle's role follows its Circle Leads and Reps: their
        assignment is the change, the circle's role isn't one besides"""
        from governance.accounts.models import User
        from governance.history.views import present

        ada = User.objects.create_user("ada@example.com", full_name="Ada")
        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        bakery = Role.objects.create(name="Bakery", is_circle=True, circle=kitchen)
        bakery.create_core_roles()
        rep = bakery.roles.get(core_role="rep")
        day = dt.date(2026, 3, 1)
        changes = [
            Change(date=day, role=rep, kind="assigned", old="", new=ada.pk),
            Change(date=day, role=bakery, kind="assigned", old="", new=ada.pk),
        ]
        self.assertEqual([c.role for c in present(changes)], [rep])
        # Alone, e.g. on the circle's own history, it stays
        self.assertEqual([c.role for c in present(changes[1:])], [bakery])


def history(*days):
    """GlassFrog's history: audit rows instead of the tests' own rows"""
    from django.db import connection

    from governance.history.backfill import backfill

    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM audit_logged_actions")
    backfill(days)


class HistoryUpdateTest(TestCase):
    def test_update_changes(self):
        cook = Role.objects.create(name="Cook")
        other = Role.objects.create(name="Other")
        policy = Policy.objects.create(role=cook, title="Tea")
        day = dt.date(2026, 1, 1)
        # The first day of the history is where it starts, not a change
        history(
            (day, {"roles": {str(other.pk): role("Other")}, "policies": {}}),
            (
                day + dt.timedelta(days=1),
                {
                    "roles": {str(other.pk): role("Other"), str(cook.pk): role("Cook")},
                    "policies": {
                        str(policy.pk): {"title": "Tea", "body": "", "role": cook.pk}
                    },
                },
            ),
            (
                day + dt.timedelta(days=2),
                {
                    "roles": {str(other.pk): role("Other"), str(cook.pk): role("Chef")},
                    "policies": {},
                },
            ),
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


class HistoryViewsTest(TestCase):
    def test_views(self):
        from django.utils import timezone

        from governance.accounts.models import User
        from governance.proposals.models import Proposal
        from governance.roles.models import Assignment

        user = User.objects.create_user("ada@example.com", full_name="Ada")
        self.client.force_login(user)
        circle = Role.objects.create(name="Kitchen", is_circle=True)
        cook = Role.objects.create(name="Cook", circle=circle)
        waiter = Role.objects.create(name="Waiter", circle=circle)
        policy = Policy.objects.create(role=circle, title="Tea")
        # Holders come from the assignments
        Assignment.objects.create(role=cook, user=user, ends_on=dt.date(2026, 1, 2))
        day = dt.date(2026, 1, 1)
        base = {
            str(circle.pk): role("Kitchen", is_circle=True),
            str(cook.pk): role(
                "Kok", circle=circle.pk, accountabilities=["Frying", None]
            ),
        }
        history(
            (day, {"roles": base, "policies": {}}),
            (
                day + dt.timedelta(days=1),
                {
                    "roles": base
                    | {
                        str(cook.pk): role("Cook", circle=circle.pk, purpose="Food"),
                        str(waiter.pk): role("Waiter", circle=circle.pk),
                    },
                    "policies": {
                        str(policy.pk): {
                            "title": "Tea",
                            "body": "Always",
                            "role": circle.pk,
                        }
                    },
                },
            ),
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
        self.assertContains(
            self.client.get(f"/roles/{waiter.pk}/as-of/?date=2026-01-01"),
            "didn't exist",
        )


class TimelineTest(TestCase):
    def test_local_days(self):
        """Proposals are on their local day like the changes, also when
        decided shortly after midnight"""
        from governance.history.views import timeline
        from governance.proposals.models import Proposal

        proposal = Proposal(
            tension="Night owls",
            decided_at=dt.datetime(2026, 11, 6, 23, 30, tzinfo=dt.UTC),
        )
        self.assertEqual(timeline([], [proposal])[0][0], dt.date(2026, 11, 7))


class FairyTasksTest(TestCase):
    def test_changes_of_the_app(self):
        """Changes made in the app are audit rows: the daily task turns them
        into the history's changes"""
        from django.core.management import call_command
        from django.utils import timezone

        from governance.accounts.models import User
        from governance.history.audit import structure_from_database
        from governance.roles.models import Accountability, Assignment

        ada = User.objects.create_user("ada@example.com", full_name="Ada")
        circle = Role.objects.create(name="Kitchen", is_circle=True)
        circle.create_core_roles()
        cook = Role.objects.create(name="Cook", circle=circle)
        Accountability.objects.create(role=cook, text="Cooking")
        Assignment.objects.create(role=cook, user=ada, focus="Soup")
        Policy.objects.create(role=circle, title="Tea", body="Always")
        day = timezone.localdate() - dt.timedelta(days=5)

        data = structure_from_database(day)
        entry = data["roles"][str(cook.pk)]
        self.assertEqual(
            (entry["name"], entry["circle"], entry["accountabilities"]),
            ("Cook", circle.pk, ["Cooking"]),
        )
        secretary = circle.roles.get(core_role="secretary")
        # Constitutional texts like in GlassFrog's history, in English
        self.assertIn(
            "Scheduling Governance Meetings for the Circle",
            data["roles"][str(secretary.pk)]["accountabilities"],
        )
        history((day, data))

        cook.name = "Chef"
        cook.save()
        call_command("fairy_tasks")
        self.assertEqual(
            list(Change.objects.filter(role=cook).values_list("kind", "old", "new")),
            [("name", "Cook", "Chef")],
        )
        self.assertEqual(Change.objects.get(role=cook).date, timezone.localdate())
