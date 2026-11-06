from django.test import TestCase
from django.utils import timezone

from governance.accounts.models import User
from governance.meetings.models import Meeting
from governance.proposals.drafting import can_edit
from governance.proposals.models import Proposal
from governance.roles.models import Role


class CanEditTest(TestCase):
    def test_can_edit(self):
        """Proposers change their drafts; the secretary amends others'
        proposals only while the meeting processing them runs"""
        ada = User.objects.create_user("ada@example.com")
        bob = User.objects.create_user("bob@example.com")
        eve = User.objects.create_user("eve@example.com")
        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        draft = Proposal.objects.create(
            circle=kitchen, proposer=bob, tension="Soup", created_at=timezone.now()
        )
        self.assertTrue(can_edit(bob, draft))
        self.assertFalse(can_edit(ada, draft))

        meeting = Meeting.objects.create(
            circle=kitchen,
            kind=Meeting.GOVERNANCE,
            started_at=timezone.now(),
            secretary=ada,
        )
        draft.status, draft.meeting = Proposal.IN_MEETING, meeting
        self.assertTrue(can_edit(ada, draft))  # The secretary, in the meeting
        self.assertFalse(can_edit(bob, draft))  # The proposer only for drafts
        self.assertFalse(can_edit(eve, draft))

        draft.status = Proposal.PUBLISHED
        self.assertFalse(can_edit(ada, draft))
        draft.status = Proposal.IN_MEETING
        meeting.ended_at = timezone.now()
        self.assertFalse(can_edit(ada, draft))  # Not after the meeting


class ProblemsTest(TestCase):
    def test_each_problem_once(self):
        """Several instructions about a missing role report it once"""
        from governance.proposals.instructions import problems

        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        proposal = Proposal(
            circle=kitchen,
            instructions=[
                {"op": "test", "path": "/roles/999999"},
                {"op": "remove", "path": "/roles/999999/domains/1"},
            ],
            names={"roles/999999": "Baker"},
        )
        self.assertEqual(problems(proposal), ["Baker doesn't exist anymore."])

    def test_no_empty_names(self):
        """Names, titles, accountabilities and domains aren't emptied, e.g.
        from the API; purposes and policies' bodies may be empty"""
        from governance.proposals.instructions import problems
        from governance.roles.models import Policy

        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        cook = Role.objects.create(name="Cook", circle=kitchen)
        tea = Policy.objects.create(role=kitchen, title="Tea")
        for instruction in [
            {"op": "replace", "path": f"/roles/{cook.pk}/name", "value": " "},
            {"op": "replace", "path": f"/policies/{tea.pk}/title"},
            {"op": "add", "path": f"/roles/{cook.pk}/accountabilities/n1"},
        ]:
            with self.subTest(instruction=instruction):
                proposal = Proposal(circle=kitchen, instructions=[instruction])
                self.assertEqual(len(problems(proposal)), 1)
        proposal = Proposal(
            circle=kitchen,
            instructions=[
                {"op": "replace", "path": f"/roles/{cook.pk}/aim", "value": ""},
                {"op": "replace", "path": f"/policies/{tea.pk}/body", "value": ""},
            ],
        )
        self.assertEqual(problems(proposal), [])

    def test_holder_with_two_focuses_leads_once(self):
        """The role's holders lead the new circle, each once"""
        from governance.accounts.models import User
        from governance.proposals.instructions import adopt
        from governance.roles.models import Assignment

        ada = User.objects.create_user("ada@example.com", full_name="Ada")
        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        cook = Role.objects.create(name="Cook", circle=kitchen)
        for focus in ["Soups", "Sauces"]:
            Assignment.objects.create(role=cook, user=ada, focus=focus)
        adopt(
            Proposal.objects.create(
                circle=kitchen,
                proposer=ada,
                tension="Bigger",
                created_at=timezone.now(),
                instructions=[
                    {"op": "add", "path": f"/roles/{cook.pk}/supporting_circle"}
                ],
            )
        )
        lead = cook.roles.get(core_role="lead")
        self.assertEqual(Assignment.objects.current().filter(role=lead).count(), 1)

    def test_conflict_markers(self):
        """Texts with conflict markers aren't adopted, e.g. from the API"""
        from governance.proposals.instructions import problems

        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        cook = Role.objects.create(name="Cook", circle=kitchen)
        proposal = Proposal(
            circle=kitchen,
            instructions=[
                {
                    "op": "replace",
                    "path": f"/roles/{cook.pk}/aim",
                    "original_value": "",
                    "value": "<<<<<<< currently\nSoup\n=======\nStew\n>>>>>>> proposal",
                },
            ],
        )
        self.assertEqual(
            problems(proposal), ["Cook: purpose still contains conflict markers."]
        )
        # Equals signs elsewhere are fine
        proposal.instructions[0]["value"] = "a ======= b"
        self.assertEqual(problems(proposal), [])

    def test_supporting_circle_only_add_and_remove(self):
        """Other operations on a role's circle aren't conversions"""
        from governance.proposals.instructions import problems

        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        bakery = Role.objects.create(name="Bakery", is_circle=True, circle=kitchen)
        Role.objects.create(name="Baker", circle=bakery)
        path = f"/roles/{bakery.pk}/supporting_circle"
        for op in ["test", "replace"]:
            proposal = Proposal(circle=kitchen, instructions=[{"op": op, "path": path}])
            with self.subTest(op=op):
                self.assertEqual(
                    problems(proposal), [f"The app can't apply {path} yet."]
                )

    def test_new_circle_like_glassfrog(self):
        """GlassFrog turns a new role into a circle twice, before and after
        moving roles into it"""
        from governance.proposals.instructions import problems

        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        kitchen.create_core_roles()
        cook = Role.objects.create(name="Cook", circle=kitchen)
        circle = {"op": "add", "path": "/roles/n1/supporting_circle"}
        proposal = Proposal(
            circle=kitchen,
            instructions=[
                {"op": "add", "path": "/roles/n1"},
                {"op": "add", "path": "/roles/n1/name", "value": "Pantry"},
                circle,
                {
                    "op": "move",
                    "from": f"/roles/{cook.pk}",
                    "path": f"/roles/n1/supporting_circle/roles/{cook.pk}",
                },
                circle | {"context": {"related_instruction": {"op": "add"}}},
            ],
        )
        self.assertEqual(problems(proposal), [])


class DescribeTest(TestCase):
    def test_moving_into_a_new_circle(self):
        """Roles moved into a circle the proposal creates read like moves"""
        from governance.proposals.describe import describe

        changes = describe(
            [
                {"op": "add", "path": "/roles/n1"},
                {"op": "add", "path": "/roles/n1/name", "value": "Pantry"},
                {"op": "add", "path": "/roles/n1/supporting_circle"},
                {
                    "op": "move",
                    "from": "/roles/5",
                    "path": "/roles/n1/supporting_circle/roles/5",
                },
            ],
            {"roles/5": "Cook", "roles/n1": "Pantry"},
        )
        moved = [c for c in changes if c.action == "moved"]
        self.assertEqual(
            [(c.label, c.subject, c.new) for c in moved], [("Role", "Cook", "Pantry")]
        )


class CircleRepMovedUnderOwnLeadTest(TestCase):
    def test_moved_under_its_circle_reps_lead(self):
        """A circle without a Circle Lead of its own is led from above
        (1.4.2): moved under a circle its Circle Rep leads, the Circle Rep
        resigns (5.1.1), after the draft warned"""
        from django.core import mail

        from governance.proposals.instructions import adopt
        from governance.roles.models import Assignment

        ada = User.objects.create_user("ada@example.com", full_name="Ada")
        eve = User.objects.create_user("eve@example.com", full_name="Eve")
        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        kitchen.create_core_roles()
        Assignment.objects.create(role=kitchen.roles.get(core_role="lead"), user=ada)
        Assignment.objects.create(role=kitchen, user=ada)
        pantry = Role.objects.create(name="Pantry", circle=kitchen, is_circle=True)
        pantry.create_core_roles()
        Role.objects.create(name="Shelves", circle=pantry)
        Assignment.objects.create(role=pantry.roles.get(core_role="lead"), user=eve)
        bakery = Role.objects.create(name="Bakery", circle=kitchen, is_circle=True)
        bakery.create_core_roles()
        Role.objects.create(name="Baker", circle=bakery)
        representing = Assignment.objects.create(
            role=bakery.roles.get(core_role="rep"),
            user=eve,
            starts_on=timezone.localdate() - timezone.timedelta(days=30),
        )
        proposal = Proposal.objects.create(
            circle=kitchen,
            proposer=ada,
            tension="Bread belongs to the pantry",
            created_at=timezone.now(),
            instructions=[
                {
                    "op": "move",
                    "path": f"/roles/{pantry.pk}/supporting_circle/roles/{bakery.pk}",
                }
            ],
        )
        self.client.force_login(ada)
        response = self.client.get(proposal.get_absolute_url())
        self.assertContains(
            response,
            "Eve would lead Bakery while being its Circle Rep: adopting the proposal"
            " ends that assignment",
        )

        with self.captureOnCommitCallbacks(execute=True):
            adopt(proposal)
        representing.refresh_from_db()
        self.assertEqual(representing.ends_on, timezone.localdate())
        self.assertIn("eve@example.com", [m.to[0] for m in mail.outbox])
