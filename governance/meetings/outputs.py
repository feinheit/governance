"""The outputs of a meeting, for its mail and its page once it ended"""

from governance.proposals.describe import describe


def meeting_outputs(meeting):
    """Adopted proposals with their changes and elections, or the outcomes
    of a tactical meeting's tensions"""
    # Decided in the meeting, not afterwards (e.g. withdrawn while waiting
    # for the next meeting)
    decided = {"decided_at__gte": meeting.started_at}
    if meeting.ended_at:
        decided["decided_at__lte"] = meeting.ended_at
    proposals = (
        [
            {
                "proposal": proposal,
                "changes": describe(proposal.instructions, proposal.names),
            }
            for proposal in meeting.proposals.filter(
                status="adopted", **decided
            ).order_by("decided_at")
        ]
        if meeting.started_at
        else []
    )
    # Discarded in the meeting (5.3.1, 5.3.4) or withdrawn by their proposers
    withdrawn = (
        list(
            meeting.proposals.filter(status="withdrawn", **decided).order_by(
                "decided_at"
            )
        )
        if meeting.started_at
        else []
    )
    return {
        "proposals": proposals,
        "withdrawn": withdrawn,
        "elections": list(meeting.elections.select_related("role", "user")),
        "outcomes": [
            item
            for item in meeting.agenda_items.select_related("owner")
            if item.outcome or item.link
        ],
    }
