"""What meetings were about, for their lists: the adopted proposals of
governance meetings, else the agenda items"""

from django.db.models import Prefetch

from governance.meetings.models import AgendaItem


def with_teasers(meetings, shown=3):
    """The meetings with ``teaser`` (up to ``shown`` texts) and
    ``teaser_more`` (how many more)"""
    from governance.proposals.models import Proposal

    meetings = list(
        meetings.prefetch_related(
            Prefetch(
                "agenda_items",
                queryset=AgendaItem.objects.select_related("proposal").order_by(
                    "position", "pk"
                ),
                to_attr="teaser_items",
            ),
            Prefetch(
                "proposals",
                queryset=Proposal.objects.filter(status=Proposal.ADOPTED).order_by(
                    "decided_at", "pk"
                ),
                to_attr="adopted_proposals",
            ),
        )
    )
    for meeting in meetings:
        texts = [str(proposal) for proposal in meeting.adopted_proposals] or [
            text for item in meeting.teaser_items if (text := str(item))
        ]
        meeting.teaser = texts[:shown]
        meeting.teaser_more = max(0, len(texts) - shown)
    return meetings
