import datetime as dt
import json
import subprocess
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings
from django.utils import timezone

from governance.accounts.models import User
from governance.glassfrog.export import ENDPOINTS, ApiExport, Export
from governance.glassfrog.importer import import_glassfrog
from governance.glassfrog.normalize import normalize
from governance.history.models import Change, Snapshot
from governance.history.snapshots import build_snapshot, canonical
from governance.meetings.models import Meeting
from governance.proposals.instructions import problems
from governance.proposals.models import Proposal
from governance.roles.models import (
    Accountability,
    Assignment,
    ChecklistItem,
    Domain,
    Metric,
    Policy,
    Role,
)


ADA = {"id": 1, "name": "Ada Example", "email": "ada@example.com"}
BOB = {"id": 2, "name": "Bob Example", "email": "bob@example.com"}
REDACTED_BOB = {"id": 2, "name": "Removed", "email": "[redacted]-abc"}
EVE = {"id": 3, "name": "Removed", "email": "[redacted]-xyz"}


def role(
    id,
    name,
    circle,
    *,
    people=(),
    accountabilities=(),
    domains=(),
    supporting=None,
    core=False,
    **kwargs,
):
    return {
        "id": id,
        "name": name,
        "purpose": kwargs.pop("purpose", f"Purpose of {name}"),
        "is_core": core,
        "links": {
            "circle": circle,
            "supporting_circle": supporting,
            "people": list(people),
            "accountabilities": list(accountabilities),
            "domains": list(domains),
        },
        **kwargs,
    }


def circle(id, name, supported_role, policies=()):
    return {
        "id": id,
        "name": name,
        "short_name": name,
        "strategy": f"Strategy of {name}",
        "links": {"supported_role": supported_role, "policies": list(policies)},
    }


def snapshot(*, kitchen=True, bob_cooks=True, cook_name="Cook"):
    roles = [
        {},
        role(100, "Example Ltd", None, supporting=10, people=[1]),
        role(
            101,
            "Secretary",
            10,
            core=True,
            people=[1],
            elected_until="2027-01-01",
            accountabilities=[901],
            domains=[801],
        ),
        role(
            102,
            "Kitchen",
            10,
            supporting=20 if kitchen else None,
            people=[1],
            accountabilities=[902],
        ),
        role(103, "Cleaner", 10, people=[1, 2], purpose="Clean after the @Cook"),
    ]
    circles = [
        circle(10, "Example Ltd", 100, policies=[500]),
        # A stale circle: the supported role doesn't point back to it
        circle(30, "Stale", 103),
    ]
    if kitchen:
        roles.append(
            role(
                104,
                cook_name,
                20,
                people=[2] if bob_cooks else [],
                accountabilities=[903],
            )
        )
        circles.append(circle(20, "Kitchen", 102))
    return {
        "circles": circles,
        "linked": {
            "roles": roles,
            "policies": [
                {},
                {
                    "id": 500,
                    "title": "Tea",
                    "body": "Always",
                    "links": {"circle": 10, "role": None, "domain": None},
                },
            ],
            "domains": [
                {},
                {"id": 801, "description": "All governance records of the Circle"},
            ],
            "people": [{}, ADA, BOB],
        },
    }


def current_files():
    return {
        "roles.json": {
            "roles": [
                {
                    "id": 102,
                    "purpose": "Food for everyone",
                    "links": {"accountabilities": [902], "domains": [802]},
                },
                {"id": 101, "links": {"accountabilities": [901], "domains": [801]}},
                {"id": 103, "links": {"accountabilities": [], "domains": []}},
            ],
            "linked": {
                "accountabilities": [
                    {},
                    {
                        "id": 901,
                        "description": "Scheduling Governance Meetings for the Circle",
                    },
                    {"id": 902, "description": "Cooking"},
                ],
                "domains": [
                    {},
                    {"id": 801, "description": "All governance records of the Circle"},
                    {"id": 802, "description": "The fridge"},
                ],
                "people": [{}, ADA, REDACTED_BOB],
            },
        },
        "assignments.json": {
            "assignments": [
                {
                    "id": 1001,
                    "focus": "Windows",
                    "election": None,
                    "links": {"role": 103, "person": 2},
                },
                {
                    "id": 1002,
                    "focus": "",
                    "election": "2027-01-01",
                    "links": {"role": 101, "person": 1},
                },
                {
                    "id": 1003,
                    "focus": "",
                    "election": None,
                    "links": {"role": 102, "person": 2},
                },
            ],
            "linked": {},
        },
        "policies.json": {
            "policies": [
                {
                    "id": 500,
                    "title": "Tea",
                    "body": "Always, also in the afternoon",
                    "links": {"circle": 10},
                },
                {
                    "id": 501,
                    "title": "Fridge",
                    "body": "Clean",
                    "links": {"circle": 10, "role": 102, "domain": 802},
                },
            ],
            "linked": {},
        },
        "proposals.json": {
            "proposals": [
                {
                    "id": 700,
                    "status": "accepted",
                    "accepted_at": "2026-02-01T10:00:00Z",
                    "proposed_at": "2026-01-28T10:00:00Z",
                    "response_deadline": "2026-02-01T10:00:00Z",
                    "instructions": [
                        {"op": "remove", "path": "/roles/104"},
                        {"op": "add", "path": "/roles/105"},
                        {"op": "add", "path": "/roles/105/name", "value": "Baker"},
                        {
                            "op": "replace",
                            "path": "/roles/102/accountabilities/902/description",
                            "original_value": "Cook",
                            "value": "Cooking",
                        },
                    ],
                    "links": {"circle": 10, "tension": 600, "person": 1},
                },
                {
                    "id": 701,
                    "status": "draft",
                    "instructions": [],
                    "links": {"circle": 99, "tension": None, "person": 3},
                },
                # Waiting for a governance meeting for months, and recently
                {
                    "id": 702,
                    "status": "escalated",
                    "proposed_at": "2025-12-01T10:00:00Z",
                    "instructions": [],
                    "links": {"circle": 10, "tension": None, "person": 1},
                },
                # A draft, its instructions with GlassFrog's IDs
                {
                    "id": 705,
                    "status": "draft",
                    "proposed_at": "2026-02-25T10:00:00Z",
                    "instructions": [
                        {"op": "test", "path": "/roles/102"},
                        {
                            "op": "remove",
                            "path": "/roles/102/domains/802",
                            "original_value": "The fridge",
                        },
                        {
                            "op": "add",
                            "path": "/roles/102/accountabilities/999",
                            "value": "Asking [@Kitchen](/organizations/1/orgnav/roles/102)",
                        },
                        # GlassFrog adds accountabilities with /description too
                        {
                            "op": "add",
                            "path": "/roles/102/accountabilities/998/description",
                            "value": "Washing up",
                        },
                    ],
                    "links": {"circle": 10, "tension": None, "person": 1},
                },
                {
                    "id": 703,
                    "status": "escalated",
                    "proposed_at": "2026-02-20T10:00:00Z",
                    "instructions": [],
                    "links": {"circle": 10, "tension": None, "person": 1},
                },
            ],
            "linked": {
                "tensions": [
                    {},
                    {
                        "id": 600,
                        "body": "No bread",
                        "created_at": "2026-01-27T09:00:00Z",
                    },
                ],
                "people": [{}, ADA, EVE],
                "circles": [],
            },
        },
        "tensions.json": {
            "tensions": [
                {
                    "id": 601,
                    "body": "Too loud",
                    "created_at": "2026-03-01T09:00:00Z",
                    "links": {"circle": 10, "person": 1, "proposal": None},
                },
                {
                    "id": 602,
                    "body": "Has a proposal",
                    "created_at": "2026-03-01T09:00:00Z",
                    "links": {"circle": 10, "person": 1, "proposal": 700},
                },
            ],
            "linked": {},
        },
        "governance_meetings.json": {
            "governance_meetings": [
                {
                    "id": 300,
                    "started_at": "2026-02-01T09:00:00Z",
                    "ended_at": "2026-02-01T10:00:00Z",
                    "scratch_pad": "Notes",
                    "links": {"circle": 10},
                },
                {
                    "id": 301,
                    "started_at": "2019-02-01T09:00:00Z",
                    "ended_at": None,
                    "scratch_pad": None,
                    "links": {"circle": None},
                },
            ],
            "linked": {
                "agenda_items": [
                    {},
                    {
                        "id": 400,
                        "position": 1,
                        "label": "Bread",
                        "completed": True,
                        "links": {"meeting": 300, "person": 1, "proposal": 700},
                    },
                ]
            },
        },
        "tactical_meetings.json": {
            "tactical_meetings": [
                {
                    "id": 300,
                    "started_at": "2026-02-02T09:00:00Z",
                    "ended_at": None,
                    "scratch_pad": None,
                    "links": {"circle": 10},
                }
            ],
            "linked": {
                "agenda_items": [
                    {
                        "id": 410,
                        "position": 1,
                        "label": "Dishes",
                        "completed": False,
                        "links": {"meeting": 300, "person": 2, "proposal": None},
                    }
                ]
            },
        },
        "metrics.json": {
            "metrics": [
                {
                    "id": 200,
                    "description": "Cups of tea",
                    "frequency": "Weekly",
                    "link": "https://example.com/",
                    "links": {"circle": 10, "role": 103},
                }
            ]
        },
        "checklist_items.json": {
            "checklist_items": [
                {
                    "id": 210,
                    "description": "Kitchen clean",
                    "frequency": "Daily",
                    "link": None,
                    "links": {"circle": 20, "role": None},
                },
                {
                    "id": 211,
                    "description": "Kindness",
                    "frequency": "Weekly",
                    "link": None,
                    "links": {"circle": None, "role": None},
                },
            ]
        },
    }


def commit(path, files, message):
    for name, content in files.items():
        (path / name).write_text(json.dumps(content) if content is not None else "")
    subprocess.run(["git", "-C", path, "add", *files], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            path,
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            message,
        ],
        check=True,
    )


@override_settings(ADMINS=[("Admin", "Root@example.com")])
class ImportTest(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.directory = tempfile.TemporaryDirectory()
        path = cls.path = Path(cls.directory.name)
        subprocess.run(["git", "init", "-q", path], check=True)
        commit(
            path,
            {"glassfrog.json": snapshot(cook_name="Kok")},
            "Update data snapshot from 2026-01-01T01:00:00",
        )
        commit(
            path,
            {"glassfrog.json": snapshot()},
            "Update data snapshot from 2026-01-01T12:00:00",
        )
        commit(
            path,
            {"glassfrog.json": None},
            "Update data snapshot from 2026-01-15T01:00:00",
        )
        commit(
            path,
            {"glassfrog.json": snapshot(bob_cooks=False)},
            "Update data snapshot from 2026-02-01T01:00:00",
        )
        commit(
            path,
            {"glassfrog.json": snapshot(kitchen=False)} | current_files(),
            "Update data snapshot from 2026-03-01T01:00:00+00:00",
        )

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()
        super().tearDownClass()

    def test_export(self):
        days = [day for day, _data in Export(self.path).snapshots()]
        # The empty snapshot is skipped, the last one of a day wins
        self.assertEqual(
            days, [dt.date(2026, 1, 1), dt.date(2026, 2, 1), dt.date(2026, 3, 1)]
        )
        self.assertIsNone(Export(self.path).load("missing.json"))

    def test_normalize(self):
        data = normalize(snapshot())
        self.assertEqual(set(data["roles"]), {100, 101, 102, 103, 104})
        self.assertEqual(data["circle_roles"], {10: 100, 20: 102})
        self.assertTrue(data["roles"][102]["is_circle"])
        self.assertEqual(data["roles"][104]["circle"], 102)
        self.assertEqual(data["roles"][101]["core_role"], "secretary")
        self.assertEqual(data["policies"][500]["role"], 100)

        # A circle with only its core roles is a role
        only_core = snapshot()
        for role in only_core["linked"]["roles"]:
            if role and role["id"] == 104:
                role["name"], role["is_core"] = "Secretary", True
        data = normalize(only_core)
        self.assertFalse(data["roles"][102]["is_circle"])
        self.assertNotIn(104, data["roles"])
        self.assertTrue(data["roles"][100]["is_circle"])  # Not the anchor

    def test_import(self):
        stats = import_glassfrog(self.path, log=lambda message: None)
        self.assertEqual(stats["snapshots"], 3)

        anchor = Role.objects.get(glassfrog_id=100)
        self.assertEqual(
            (anchor.circle, anchor.is_circle, anchor.glassfrog_circle_id),
            (None, True, 10),
        )
        kitchen = Role.objects.get(glassfrog_id=102)
        # Turned back into a role, the purpose comes from roles.json
        self.assertEqual(
            (kitchen.is_circle, kitchen.circle, kitchen.purpose),
            (False, anchor, "Food for everyone"),
        )
        cook = Role.objects.get(glassfrog_id=104)
        self.assertEqual(
            (cook.name, cook.circle, cook.archived_on),
            ("Cook", kitchen, dt.date(2026, 3, 1)),
        )
        secretary = Role.objects.get(glassfrog_id=101)
        self.assertEqual((secretary.core_role, secretary.position), ("secretary", 2))

        # Constitutional texts of core roles aren't stored
        self.assertFalse(Accountability.objects.filter(role=secretary).exists())
        self.assertFalse(Domain.objects.filter(role=secretary).exists())
        self.assertEqual(
            list(kitchen.accountabilities.values_list("text", flat=True)), ["Cooking"]
        )
        fridge = Domain.objects.get(glassfrog_id=802)

        tea = Policy.objects.get(glassfrog_id=500)
        self.assertEqual(
            (tea.role, tea.body, tea.archived_on),
            (anchor, "Always, also in the afternoon", None),
        )
        fridge_policy = Policy.objects.get(glassfrog_id=501)
        self.assertEqual((fridge_policy.role, fridge_policy.domain), (kitchen, fridge))

        # People: redacted in the current files, but known from the snapshots
        ada = User.objects.get(email="ada@example.com")
        bob = User.objects.get(email="bob@example.com")
        self.assertEqual(
            (ada.is_active, bob.full_name, bob.is_active), (True, "Bob Example", False)
        )
        self.assertFalse(User.objects.filter(full_name="Removed").exists())
        admin = User.objects.get(email="root@example.com")
        self.assertTrue(admin.is_admin)

        bob_cooking = Assignment.objects.get(role=cook)
        self.assertEqual(
            (bob_cooking.user, bob_cooking.starts_on, bob_cooking.ends_on),
            (bob, None, dt.date(2026, 2, 1)),
        )
        cleaning = Assignment.objects.get(role__glassfrog_id=103, user=bob)
        self.assertEqual(
            (cleaning.focus, cleaning.glassfrog_id, cleaning.ends_on),
            ("Windows", 1001, None),
        )
        self.assertEqual(
            Assignment.objects.get(role=secretary).elected_until, dt.date(2027, 1, 1)
        )
        # Not in the snapshots, only in assignments.json
        self.assertEqual(Assignment.objects.get(glassfrog_id=1003).starts_on, None)

        self.assertEqual(Metric.objects.get().role.glassfrog_id, 103)
        # The circle was turned back into a role, the item stays with it
        self.assertEqual(ChecklistItem.objects.get(glassfrog_id=210).role, kitchen)
        # Neither circle nor role: the whole organization's
        kindness = ChecklistItem.objects.get(glassfrog_id=211)
        self.assertEqual((kindness.role, kindness.frequency), (anchor, "weekly"))

        proposal = Proposal.objects.get(glassfrog_id=700)
        self.assertEqual(
            (proposal.circle, proposal.proposer, proposal.tension),
            (anchor, ada, "No bread"),
        )
        self.assertEqual(proposal.status, Proposal.ADOPTED)
        self.assertEqual(
            proposal.names,
            {
                "roles/104": "Cook",
                "roles/105": "Baker",
                "roles/102": "Kitchen",
                "accountabilities/902": "Cooking",
            },
        )
        self.assertEqual(str(proposal), "No bread")
        self.assertFalse(
            Proposal.objects.filter(glassfrog_id=701).exists()
        )  # Unknown circle
        tension = Proposal.objects.get(glassfrog_tension_id=601)
        self.assertTrue(tension.is_tension)
        self.assertFalse(Proposal.objects.filter(glassfrog_tension_id=602).exists())

        meeting = Meeting.objects.get(kind=Meeting.GOVERNANCE, glassfrog_id=300)
        self.assertEqual((meeting.circle, meeting.minutes), (anchor, "Notes"))
        self.assertEqual(
            list(meeting.agenda_items.values_list("label", "owner", "is_completed")),
            [("Bread", ada.pk, True)],
        )
        proposal.refresh_from_db()
        self.assertEqual(proposal.meeting, meeting)
        self.assertIsNone(Meeting.objects.get(glassfrog_id=301).circle)
        self.assertEqual(
            Meeting.objects.get(kind=Meeting.TACTICAL).agenda_items.get().owner, bob
        )

        first = Snapshot.objects.get(date=dt.date(2026, 1, 1)).data
        self.assertEqual(
            first["roles"][str(cook.pk)]["assignments"],
            [{"user": bob.pk, "elected_until": None}],
        )
        self.assertEqual(
            first["roles"][str(kitchen.pk)]["accountabilities"], ["Cooking"]
        )
        self.assertEqual(
            first["roles"][str(cook.pk)]["accountabilities"], [None]
        )  # Unknown text
        self.assertEqual(first["policies"][str(tea.pk)]["body"], "Always")
        # Mentions like in the database
        self.assertEqual(
            first["roles"][str(Role.objects.get(glassfrog_id=103).pk)]["purpose"],
            f"Clean after the @[Cook](role:{cook.pk})",
        )
        # The newest snapshot is the database's state
        self.assertEqual(
            canonical(Snapshot.objects.get(date=dt.date(2026, 3, 1)).data),
            canonical(build_snapshot(dt.date(2026, 3, 1))),
        )
        self.assertEqual(
            Snapshot.objects.on(dt.date(2026, 1, 20)).date, dt.date(2026, 1, 1)
        )

        # Idempotent
        counts = [
            model.objects.count()
            for model in [Role, Assignment, Policy, Proposal, Meeting, Snapshot, User]
        ]
        import_glassfrog(self.path, log=lambda message: None)
        self.assertEqual(
            counts,
            [
                model.objects.count()
                for model in [
                    Role,
                    Assignment,
                    Policy,
                    Proposal,
                    Meeting,
                    Snapshot,
                    User,
                ]
            ],
        )

    def test_old_escalated_proposals(self):
        """Escalated proposals nobody brought to a meeting for two months go
        back to their proposers as drafts, unless they're on an agenda here"""
        import_glassfrog(self.path, log=lambda message: None)
        old = Proposal.objects.get(glassfrog_id=702)
        self.assertEqual(old.status, Proposal.DRAFT)
        recent = Proposal.objects.get(glassfrog_id=703)
        self.assertEqual(recent.status, Proposal.IN_MEETING)

        old.status = Proposal.IN_MEETING
        old.meeting = Meeting.objects.create(
            circle=old.circle,
            kind=Meeting.GOVERNANCE,
            started_at=timezone.now(),
            ended_at=timezone.now(),
        )
        old.save()
        import_glassfrog(self.path, log=lambda message: None)
        old.refresh_from_db()
        self.assertEqual(old.status, Proposal.IN_MEETING)

    def test_open_proposals_with_the_apps_ids(self):
        """Proposals which aren't adopted yet will be adopted here: the import
        translates GlassFrog's IDs in their instructions to the app's"""
        import_glassfrog(self.path, log=lambda message: None)
        draft = Proposal.objects.get(glassfrog_id=705)
        kitchen = Role.objects.get(glassfrog_id=102)
        fridge = Domain.objects.get(glassfrog_id=802)
        self.assertEqual(
            [i["path"] for i in draft.instructions],
            [
                f"/roles/{kitchen.pk}",
                f"/roles/{kitchen.pk}/domains/{fridge.pk}",
                f"/roles/{kitchen.pk}/accountabilities/n1",
                f"/roles/{kitchen.pk}/accountabilities/n2/description",
            ],
        )
        # Mentions like in the current texts, not GlassFrog's links
        self.assertEqual(
            draft.instructions[2]["value"], f"Asking @[Kitchen](role:{kitchen.pk})"
        )
        self.assertEqual(draft.names[f"roles/{kitchen.pk}"], "Kitchen")
        self.assertEqual(problems(draft), [])

    def test_incremental_import(self):
        """Today's state from the API, added to the history in the database"""
        import_glassfrog(self.path, log=lambda message: None)
        ada = User.objects.get(email="ada@example.com")
        bob = User.objects.get(email="bob@example.com")
        self.assertEqual((ada.glassfrog_id, bob.glassfrog_id), (1, 2))

        # The Kitchen is renamed, the Cleaner removed, a Dishwasher added,
        # Bob only shows up redacted, the Tea policy is gone
        data = snapshot(kitchen=False)
        roles = data["linked"]["roles"]
        roles[3]["name"] = "Galley"
        roles[4] = role(106, "Dishwasher", 10, people=[2])
        data["linked"]["people"] = [{}, ADA, REDACTED_BOB]
        data["linked"]["policies"] = [{}]
        data["circles"][0]["links"]["policies"] = []
        files = current_files()
        files["roles.json"]["roles"][0]["purpose"] = "Like the @Kitchen before"
        files["assignments.json"]["assignments"] = [
            files["assignments.json"]["assignments"][1],
            {
                "id": 1004,
                "focus": "Plates",
                "election": None,
                "links": {"role": 106, "person": 2},
            },
        ]
        files["policies.json"]["policies"] = files["policies.json"]["policies"][1:]
        files["glassfrog.json"] = data
        endpoints = {endpoint: name for name, endpoint in ENDPOINTS.items()}
        day = dt.date(2026, 3, 10)
        export = ApiExport(
            "token", day=day, fetch=lambda path, token: files[endpoints[path]]
        )

        stats = import_glassfrog(export, log=lambda message: None)
        self.assertEqual(stats["snapshots"], 1)
        # Eve, not Bob: the database knows him
        self.assertEqual(stats["people only known redacted"], 1)
        self.assertEqual(stats["unresolved mentions"], 0)
        self.assertEqual(Snapshot.objects.count(), 4)

        kitchen = Role.objects.get(glassfrog_id=102)
        self.assertEqual(
            (kitchen.name, kitchen.other_names, kitchen.archived_on),
            ("Galley", ["Kitchen"], None),
        )
        self.assertEqual(
            kitchen.purpose, f"Like the @[Galley](role:{kitchen.pk}) before"
        )
        self.assertEqual(Role.objects.get(glassfrog_id=103).archived_on, day)
        self.assertEqual(Policy.objects.get(glassfrog_id=500).archived_on, day)
        self.assertIsNone(Policy.objects.get(glassfrog_id=501).archived_on)

        # Redacted Bob is still Bob, the earlier assignments end today
        cleaning = Assignment.objects.get(role__glassfrog_id=103, user=bob)
        self.assertEqual(cleaning.ends_on, day)
        self.assertEqual(Assignment.objects.get(glassfrog_id=1003).ends_on, day)
        dishes = Assignment.objects.get(role__glassfrog_id=106)
        self.assertEqual(
            (dishes.user, dishes.starts_on, dishes.ends_on, dishes.focus),
            (bob, day, None, "Plates"),
        )
        # The history stays
        self.assertEqual(
            Assignment.objects.get(role__glassfrog_id=104).ends_on,
            dt.date(2026, 2, 1),
        )
        self.assertEqual(Assignment.objects.get(role__glassfrog_id=101).starts_on, None)
        self.assertEqual(
            Proposal.objects.get(glassfrog_id=700).names["roles/104"], "Cook"
        )
        self.assertTrue(Change.objects.filter(date=day, role=kitchen).exists())
        self.assertTrue(Change.objects.filter(date__lt=day).exists())

        # Idempotent
        counts = [
            model.objects.count()
            for model in [Role, Assignment, Policy, Proposal, Snapshot, User, Change]
        ]
        import_glassfrog(export, log=lambda message: None)
        self.assertEqual(
            counts,
            [
                model.objects.count()
                for model in [
                    Role,
                    Assignment,
                    Policy,
                    Proposal,
                    Snapshot,
                    User,
                    Change,
                ]
            ],
        )
        # Today's snapshot doesn't know the earlier name anymore, it stays
        kitchen.refresh_from_db()
        self.assertEqual(kitchen.other_names, ["Kitchen"])

    def test_incremental_import_archived_role(self):
        """GlassFrog still returns assignments of roles archived here (e.g. the
        core roles of circles converted to roles), they stay ended"""
        import_glassfrog(self.path, log=lambda message: None)
        day = dt.date(2026, 3, 5)
        Role.objects.filter(glassfrog_id=101).update(archived_on=day)
        Assignment.objects.filter(glassfrog_id=1002).update(ends_on=day)

        data = snapshot(kitchen=False)
        data["linked"]["roles"] = [
            r for r in data["linked"]["roles"] if r.get("id") != 101
        ]
        files = current_files() | {"glassfrog.json": data}
        endpoints = {endpoint: name for name, endpoint in ENDPOINTS.items()}
        export = ApiExport(
            "token",
            day=dt.date(2026, 3, 10),
            fetch=lambda path, token: files[endpoints[path]],
        )
        import_glassfrog(export, log=lambda message: None)

        self.assertEqual(Role.objects.get(glassfrog_id=101).archived_on, day)
        assignment = Assignment.objects.get(role__glassfrog_id=101)
        self.assertEqual((assignment.glassfrog_id, assignment.ends_on), (1002, day))


class EarlyFormatTest(TestCase):
    def test_supported_roles_and_policy_links(self):
        """Until 2019-05 snapshots had separate supported roles"""
        data = snapshot()
        roles = data["linked"]["roles"]
        data["linked"]["supported_roles"] = [r for r in roles if r and r["id"] == 100]
        data["linked"]["roles"] = [r for r in roles if not r or r["id"] != 100]
        data["linked"]["policies"][1]["links"] = {
            "circle_id": 10,
            "role_id": None,
            "domain": None,
        }
        normalized = normalize(data)
        self.assertIn(100, normalized["roles"])
        self.assertEqual(normalized["policies"][500]["role"], 100)
