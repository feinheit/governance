import datetime as dt

from django.test import TestCase
from django.utils import timezone
from django.utils.formats import date_format

from governance.accounts.models import User
from governance.proposals.describe import describe
from governance.proposals.models import Proposal
from governance.roles.models import Policy, Role


INSTRUCTIONS = [
    {"op": "test", "path": "/roles/1"},
    {"op": "add", "path": "/roles/2"},
    {"op": "add", "path": "/roles/2/name", "value": "Baker"},
    {"op": "add", "path": "/roles/2/aim", "value": "Bread"},
    {"op": "add", "path": "/roles/2/accountabilities/9/description", "value": "Baking"},
    {"op": "add", "path": "/roles/2/supporting_circle"},
    {
        "op": "replace",
        "path": "/roles/1/name",
        "original_value": "Kok",
        "value": "Cook",
    },
    {"op": "remove", "path": "/roles/1/accountabilities/8", "original_value": "Frying"},
    {"op": "add", "path": "/roles/1/domains/7/description", "value": "The stove"},
    {
        "op": "replace",
        "path": "/roles/1/accountabilities/6/description",
        "original_value": "A",
        "value": "B",
    },
    {"op": "remove", "path": "/roles/3"},
    {"op": "move", "from": "/circles/5/roles/4", "path": "/roles/4"},
    {"op": "move", "from": "/roles/4", "path": "/roles/2/supporting_circle/roles/4"},
    {"op": "remove", "path": "/roles/1/supporting_circle"},
    {
        "op": "replace",
        "path": "/roles/10/assignment/links/person",
        "original_value": "",
        "value": "Ada",
    },
    {
        "op": "replace",
        "path": "/roles/10/assignment/until",
        "original_value": "",
        "value": "2027-01-31T00:00:00.000Z",
    },
    {"op": "add", "path": "/policies/11"},
    {"op": "add", "path": "/policies/11/title", "value": "Tea"},
    {
        "op": "replace",
        "path": "/policies/12/body",
        "original_value": "Old",
        "value": "New",
    },
    {"op": "add", "path": "/policies/12/links/domain", "value": "7"},
    {"op": "add", "path": "/something/else", "value": "x"},
]
NAMES = {
    "roles/1": "Cook",
    "roles/3": "Dishwasher",
    "roles/4": "Waiter",
    "circles/5": "Hall",
    "roles/10": "Secretary",
    "policies/12": "Fridge",
    "domains/7": "The stove",
}


class ProposalsTest(TestCase):
    def test_describe(self):
        changes = [
            (c.action, c.label, c.subject, c.old, c.new, c.details)
            for c in describe(INSTRUCTIONS, NAMES)
        ]
        self.assertEqual(
            changes,
            [
                (
                    "added",
                    "Role",
                    "unknown",
                    "",
                    "",
                    [
                        ("Name", "Baker"),
                        ("Purpose", "Bread"),
                        ("Accountability", "Baking"),
                        ("Circle", "yes"),
                    ],
                ),
                ("changed", "Name", "Cook", "Kok", "Cook", []),
                ("removed", "Accountability", "Cook", "Frying", "", []),
                ("added", "Domain", "Cook", "", "The stove", []),
                ("changed", "Accountability", "Cook", "A", "B", []),
                ("removed", "Role", "Dishwasher", "", "", []),
                ("moved", "Role", "Waiter", "Hall", "", []),
                ("moved", "Role", "Waiter", "", "unknown", []),
                ("changed", "Turned back into a role", "Cook", "", "", []),
                (
                    "elected",
                    "Election",
                    "Secretary",
                    "",
                    "Ada",
                    [("until", "31.01.2027")],
                ),
                ("added", "Policy", "unknown", "", "", [("Title", "Tea")]),
                ("changed", "Text", "Fridge", "Old", "New", []),
                ("changed", "Domain", "Fridge", "", "The stove", []),
                ("changed", "/something/else", "", "", "x", []),
            ],
        )

    def test_views_and_private_drafts(self):
        ada = User.objects.create_user("ada@example.com", full_name="Ada")
        bob = User.objects.create_user("bob@example.com", full_name="Bob")
        circle = Role.objects.create(name="Kitchen", is_circle=True, glassfrog_id=100)
        cook = Role.objects.create(name="Cook", circle=circle, glassfrog_id=1)
        Policy.objects.create(role=circle, title="Fridge", glassfrog_id=12)
        now = timezone.now()
        adopted = Proposal.objects.create(
            circle=circle,
            proposer=ada,
            tension="Unclear names",
            instructions=INSTRUCTIONS,
            names=NAMES,
            status=Proposal.ADOPTED,
            created_at=now - dt.timedelta(days=2),
            decided_at=now,
            glassfrog_id=1,
        )
        adopted.roles.set([cook])
        draft = Proposal.objects.create(
            circle=circle, proposer=ada, tension="Secret idea", created_at=now
        )
        self.assertTrue(draft.is_tension)
        draft.tension = "x" * 120 + "\nSecond line"
        self.assertEqual(str(draft), "x" * 99 + "…")
        draft.tension = "## The tension\n\nNo bread\n\n## An example\n\nToday"
        self.assertEqual(str(draft), "No bread")

        self.client.force_login(bob)
        response = self.client.get("/proposals/")
        self.assertContains(response, "Unclear names")
        self.assertNotContains(response, "Secret idea")
        self.assertEqual(self.client.get(draft.get_absolute_url()).status_code, 404)

        response = self.client.get(adopted.get_absolute_url())
        self.assertContains(response, "Frying")
        self.assertContains(response, cook.get_absolute_url())  # Linked by GlassFrog ID
        self.assertContains(response, "/policies/")

        self.assertContains(
            self.client.get(f"/proposals/?role={cook.pk}"), "Unclear names"
        )
        self.assertContains(
            self.client.get(f"/proposals/?circle={circle.pk}&status=adopted"),
            "Unclear names",
        )
        self.assertContains(self.client.get(cook.get_absolute_url()), "Unclear names")

        self.client.force_login(ada)
        self.assertContains(self.client.get("/proposals/?status=draft"), "Secret idea")
        response = self.client.get(draft.get_absolute_url())
        self.assertContains(response, "created")
        self.assertContains(
            response, date_format(timezone.localtime(now), "SHORT_DATE_FORMAT")
        )


class ImportedOpenProposalTest(TestCase):
    def test_links(self):
        """Open proposals imported from GlassFrog refer to the app's IDs"""
        ada = User.objects.create_user("ada@example.com", full_name="Ada")
        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        cook = Role.objects.create(name="Cook", circle=kitchen)
        baker = Role.objects.create(name="Baker", circle=kitchen, glassfrog_id=cook.pk)
        proposal = Proposal.objects.create(
            circle=kitchen,
            proposer=ada,
            tension="Names",
            status=Proposal.PUBLISHED,
            created_at=timezone.now(),
            glassfrog_id=2,
            instructions=[
                {"op": "replace", "path": f"/roles/{cook.pk}/name", "value": "Chef"}
            ],
            names={f"roles/{cook.pk}": "Cook"},
        )
        self.client.force_login(ada)
        response = self.client.get(proposal.get_absolute_url())
        self.assertContains(response, cook.get_absolute_url())
        self.assertNotContains(response, baker.get_absolute_url())


class DatesTest(TestCase):
    def test_dates_in_order(self):
        """The latest that happened: created, published, adopted or withdrawn"""
        import re

        ada = User.objects.create_user("ada@example.com", full_name="Ada")
        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        now = timezone.now()
        proposal = Proposal.objects.create(
            circle=kitchen,
            proposer=ada,
            tension="Bread",
            status=Proposal.PUBLISHED,
            created_at=now - dt.timedelta(days=3),
            published_at=now - dt.timedelta(days=2),
            deadline=now + dt.timedelta(days=5),
        )
        self.client.force_login(ada)

        def labels():
            html = self.client.get(proposal.get_absolute_url()).content.decode()
            return re.findall(r'class="wb-meta-label"\s*>([^<]+)<', html)[1:]

        self.assertEqual(
            labels(), ["proposer", "status", "published (async)", "to be adopted on"]
        )
        proposal.status, proposal.decided_at = Proposal.ADOPTED, now
        proposal.save()
        self.assertEqual(labels(), ["proposer", "status", "adopted"])
        proposal.status = Proposal.WITHDRAWN
        proposal.save()
        self.assertEqual(labels(), ["proposer", "status", "withdrawn"])
        proposal.status, proposal.published_at, proposal.decided_at = (
            Proposal.DRAFT,
            None,
            None,
        )
        proposal.save()
        self.assertEqual(labels(), ["proposer", "status", "created"])


class ProposalTitleTest(TestCase):
    def test_without_tension(self):
        """Imported elections have no tension, the title can't be empty"""
        proposal = Proposal(tension="")
        self.assertEqual(str(proposal), "(no tension)")


class AdoptedOnTest(TestCase):
    def test_adopted_on(self):
        """The nightly task runs at 03:30 UTC"""
        proposal = Proposal(deadline=None)
        self.assertIsNone(proposal.adopted_on)
        for deadline, day in [
            (dt.datetime(2026, 12, 3, 14, tzinfo=dt.UTC), dt.date(2026, 12, 4)),
            (dt.datetime(2026, 12, 3, 2, tzinfo=dt.UTC), dt.date(2026, 12, 3)),
            (dt.datetime(2026, 12, 3, 3, 30, tzinfo=dt.UTC), dt.date(2026, 12, 3)),
            (dt.datetime(2026, 12, 3, 23, 30, tzinfo=dt.UTC), dt.date(2026, 12, 4)),
        ]:
            proposal.deadline = deadline
            self.assertEqual(proposal.adopted_on, day, deadline)
