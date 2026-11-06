import datetime as dt

from django.test import TestCase
from django.utils import timezone

from governance.accounts.models import APIToken, User
from governance.meetings.models import AgendaItem, Meeting
from governance.proposals.models import Proposal, Response
from governance.roles.models import Accountability, Assignment, Policy, Role


class BackupTest(TestCase):
    def test_backup(self):
        """Everything the token's user sees, one file per kind"""
        ada = User.objects.create_user("ada@example.com", full_name="Ada")
        bob = User.objects.create_user("bob@example.com", full_name="Bob")
        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        cook = Role.objects.create(name="Cook", circle=kitchen, glassfrog_id=7)
        Accountability.objects.create(role=cook, text="Cooking")
        Assignment.objects.create(
            role=cook, user=ada, focus="Soup", starts_on=dt.date(2026, 1, 1)
        )
        Policy.objects.create(role=kitchen, title="Tea")
        now = timezone.now()
        published = Proposal.objects.create(
            circle=kitchen,
            proposer=ada,
            tension="Bread",
            status=Proposal.PUBLISHED,
            created_at=now,
        )
        Response.objects.create(proposal=published, user=bob, kind=Response.CONSENT)
        Proposal.objects.create(
            circle=kitchen, proposer=bob, tension="Secret", created_at=now
        )
        meeting = Meeting.objects.create(
            circle=kitchen, kind=Meeting.GOVERNANCE, started_at=now, secretary=ada
        )
        AgendaItem.objects.create(meeting=meeting, label="Bread", proposal=published)
        _token, secret = APIToken.create_for(user=ada, title="Backup", access="read")

        response = self.client.get(
            "/api/backup/", headers={"authorization": f"Bearer {secret}"}
        )
        self.assertEqual(response.status_code, 200)
        files = response.json()
        self.assertEqual(
            sorted(files),
            [
                "assignments.json",
                "checklist_items.json",
                "history.json",
                "links.json",
                "meetings.json",
                "metrics.json",
                "people.json",
                "policies.json",
                "proposals.json",
                "roles.json",
            ],
        )
        role = next(r for r in files["roles.json"] if r["name"] == "Cook")
        self.assertEqual(
            (role["circle"], role["glassfrog_id"], role["accountabilities"][0]["text"]),
            (kitchen.pk, 7, "Cooking"),
        )
        self.assertEqual(files["assignments.json"][0]["starts_on"], "2026-01-01")
        # Not Bob's private draft
        self.assertEqual([p["tension"] for p in files["proposals.json"]], ["Bread"])
        self.assertEqual(files["proposals.json"][0]["responses"][0]["user"], bob.pk)
        self.assertEqual(
            files["meetings.json"][0]["agenda"][0]["proposal"], published.pk
        )
        self.assertEqual(
            {p["email"] for p in files["people.json"]},
            {"ada@example.com", "bob@example.com"},
        )
