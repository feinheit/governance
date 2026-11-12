import datetime as dt

from django.test import TestCase
from django.utils import timezone

from governance.accounts.models import APIToken, User
from governance.history.models import Change
from governance.meetings.models import AgendaItem, Meeting
from governance.proposals.models import Proposal, Response
from governance.roles.models import Accountability, Assignment, Note, Policy, Role


class BackupTest(TestCase):
    def test_backup(self):
        """Everything the token's user sees, organized by role"""
        ada = User.objects.create_user("ada@example.com", full_name="Ada")
        bob = User.objects.create_user("bob@example.com", full_name="Bob")
        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        cook = Role.objects.create(name="Cook", circle=kitchen, glassfrog_id=7)
        Accountability.objects.create(role=cook, text="Cooking")
        Assignment.objects.create(
            role=cook, user=ada, focus="Soup", starts_on=dt.date(2026, 1, 1)
        )
        Policy.objects.create(role=kitchen, title="Tea")
        Note.objects.create(role=cook, title="Pots", body="In the *cupboard*")
        now = timezone.now()
        published = Proposal.objects.create(
            circle=kitchen,
            proposer=ada,
            tension="Bread",
            status=Proposal.PUBLISHED,
            created_at=now,
        )
        Response.objects.create(proposal=published, user=bob, kind=Response.CONSENT)
        # Consents had texts before, they stay anonymous
        Response.objects.create(
            proposal=published, user=bob, kind=Response.CONSENT, text="Fine"
        )
        Response.objects.create(
            proposal=published, user=bob, kind=Response.COMMENT, text="Why?"
        )
        Proposal.objects.create(
            circle=kitchen, proposer=bob, tension="Secret", created_at=now
        )
        meeting = Meeting.objects.create(
            circle=kitchen, kind=Meeting.GOVERNANCE, started_at=now, secretary=ada
        )
        AgendaItem.objects.create(meeting=meeting, label="Bread", proposal=published)
        _token, secret = APIToken.create_for(user=ada, title="Backup", access="read")

        Policy.objects.create(
            role=kitchen, title="Old", archived_on=dt.date(2026, 2, 1)
        )
        Change.objects.create(
            date=dt.date(2026, 1, 2), role=cook, kind="name", old="Chef", new="Cook"
        )
        Meeting.objects.create(kind=Meeting.TACTICAL, started_at=now, called_by=ada)

        response = self.client.get(
            "/api/backup/", headers={"authorization": f"Bearer {secret}"}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        # The people only when asked for, the rest refers to them by ID
        self.assertEqual(sorted(data), ["meetings", "roles"])
        self.assertEqual([r["name"] for r in data["roles"]], ["Kitchen", "Cook"])
        circle, role = data["roles"]
        self.assertEqual(
            (role["circle"], role["glassfrog_id"], role["accountabilities"][0]["text"]),
            (kitchen.pk, 7, "Cooking"),
        )
        self.assertEqual(
            [(n["title"], n["body"]) for n in role["notes"]],
            [("Pots", "In the *cupboard*")],
        )
        self.assertEqual(
            [(r["user"], r["starts_on"]) for r in role["role_leads"]],
            [(ada.pk, "2026-01-01")],
        )
        self.assertEqual(
            [(c["date"], c["kind"], c["old"]) for c in role["history"]],
            [("2026-01-02", "name", "Chef")],
        )
        # Archived policies too, the circle's proposals and meetings
        self.assertEqual([p["title"] for p in circle["policies"]], ["Tea", "Old"])
        # Not Bob's private draft
        self.assertEqual([p["tension"] for p in circle["proposals"]], ["Bread"])
        self.assertEqual(role["proposals"], [])
        # Responses are anonymous like on the page, except questions and
        # concerns, which have their author
        self.assertEqual(
            [(r["kind"], r["user"]) for r in circle["proposals"][0]["responses"]],
            [
                (Response.CONSENT, None),
                (Response.CONSENT, None),
                (Response.COMMENT, bob.pk),
            ],
        )
        self.assertEqual(circle["meetings"][0]["agenda"][0]["proposal"], published.pk)
        # The ad hoc tactical meeting has no circle
        self.assertEqual([m["called_by"] for m in data["meetings"]], [ada.pk])
        self.assertNotIn("ada@example.com", response.content.decode())

        response = self.client.get(
            "/api/backup/?people=true", headers={"authorization": f"Bearer {secret}"}
        )
        self.assertEqual(
            {p["email"] for p in response.json()["people"]},
            {"ada@example.com", "bob@example.com"},
        )
