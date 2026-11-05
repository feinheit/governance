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
