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
