"""The outputs of a meeting, for its mail and its page once it ended"""

from governance.proposals.describe import describe


def meeting_outputs(meeting):
    """Adopted proposals with their changes and elections, or the outcomes
    of a tactical meeting's tensions"""
    proposals = (
        [
            {
                "proposal": proposal,
                "changes": describe(proposal.instructions, proposal.names),
            }
            for proposal in meeting.proposals.filter(
                status="adopted", decided_at__gte=meeting.started_at
            ).order_by("decided_at")
        ]
        if meeting.started_at
        else []
    )
    return {
        "proposals": proposals,
        "elections": list(meeting.elections.select_related("role", "user")),
        "outcomes": [
            item
            for item in meeting.agenda_items.select_related("owner")
            if item.outcome or item.link
        ],
    }
