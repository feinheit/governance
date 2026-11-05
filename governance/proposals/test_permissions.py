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
