"""Reading meetings, e.g. turning a tactical meeting's outcomes into tasks
in the task management tool (the ``governance-tactical`` skill)

Everybody sees all meetings, like on the pages; the API doesn't run them.
"""

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Router, Schema

from governance.meetings.models import AgendaItem, Meeting
from governance.meetings.outputs import meeting_outputs
from governance.roles.mentions import MENTION, plain_mentions
from governance.roles.models import Assignment, Role


router = Router(tags=["meetings"])

# The newest ones, ``gov meetings`` shows a page of them
LIMIT = 20


def absolute(obj):
    return settings.BASE_URL + obj.get_absolute_url()


def _iso(value):
    """In local time: the first ten characters are the day the pages show"""
    return timezone.localtime(value).isoformat() if value else None


class PersonOut(Schema):
    id: int
    name: str
    # To find them in other tools, e.g. assigning tasks
    email: str


class MentionedRoleOut(Schema):
    """A role an outcome mentions, e.g. the one taking on the next action"""

    id: int
    name: str
    circle_id: int | None
    archived: bool
    role_leads: list[PersonOut]
    url: str


class ItemOut(Schema):
    id: int
    label: str
    owner: PersonOut | None
    # Markdown, mentions as @[Name](role:ID)
    outcome: str
    # With the roles' current names, "@Name"
    outcome_plain: str
    roles: list[MentionedRoleOut]
    # E.g. the task created for it
    link: str
    proposal_id: int | None
    is_completed: bool


class LinkOut(Schema):
    """Where the projects of the circle are (``Meeting.progress_links()``)"""

    id: int
    role_id: int
    role: str
    title: str
    url: str
    description: str


class ProposalSummaryOut(Schema):
    id: int
    title: str
    url: str


class ElectionOut(Schema):
    role_id: int
    role: str
    # None: nobody, the role stays unfilled
    person: str | None
    term_ends_on: str | None


class MeetingSummaryOut(Schema):
    id: int
    # governance or tactical
    kind: str
    # A tactical meeting called with any roles, not a circle's
    ad_hoc: bool
    title: str
    circle_id: int | None
    circle: str
    started_at: str | None
    ended_at: str | None
    is_running: bool
    # Agenda items with an outcome or a link
    outcomes: int
    url: str


class MeetingOut(MeetingSummaryOut):
    secretary: str | None
    # As recorded, not necessarily who was there: not for assigning tasks
    attendees: list[PersonOut]
    invited_roles: list[ProposalSummaryOut]
    # All agenda items, those without an outcome too
    items: list[ItemOut]
    links: list[LinkOut]
    adopted: list[ProposalSummaryOut]
    withdrawn: list[ProposalSummaryOut]
    elections: list[ElectionOut]
    # Markdown
    minutes: str


def person(user):
    return {"id": user.pk, "name": str(user), "email": user.email} if user else None


def summary(meeting, outcomes):
    return {
        "id": meeting.pk,
        "kind": meeting.kind,
        "ad_hoc": meeting.is_ad_hoc,
        "title": str(meeting),
        "circle_id": meeting.circle_id,
        "circle": str(meeting.circle or ""),
        "started_at": _iso(meeting.started_at),
        "ended_at": _iso(meeting.ended_at),
        "is_running": meeting.is_running,
        "outcomes": outcomes,
        "url": absolute(meeting),
    }


@router.get("meetings/", response=list[MeetingSummaryOut])
def meetings(request, *, circle_id: int | None = None, kind: str = ""):
    """The newest meetings, those of a circle or role like its list of
    meetings (``circle_id``), ``kind`` governance, tactical or ad_hoc"""
    queryset = Meeting.objects.exclude(started_at=None)
    if circle_id:
        queryset = queryset.of_role(get_object_or_404(Role, pk=circle_id))
    if kind == "ad_hoc":
        queryset = queryset.filter(kind=Meeting.TACTICAL, circle=None)
    elif kind:
        queryset = queryset.filter(kind=kind)
    queryset = queryset.select_related("circle").order_by("-started_at")[:LIMIT]
    outcomes = {}
    for meeting_id in (
        AgendaItem.objects
        .filter(meeting__in=queryset)
        .exclude(outcome="", link="")
        .values_list("meeting", flat=True)
    ):
        outcomes[meeting_id] = outcomes.get(meeting_id, 0) + 1
    return [summary(meeting, outcomes.get(meeting.pk, 0)) for meeting in queryset]


@router.get("meetings/{int:pk}/", response=MeetingOut)
def meeting(request, pk: int):
    """A meeting with its agenda items, their outcomes and the roles they
    mention with their Role Leads, the links of the circle (an ad hoc
    meeting's of the invited roles' circles), and its outputs"""
    meeting = get_object_or_404(
        Meeting.objects.select_related("circle", "secretary"), pk=pk
    )
    items = list(meeting.agenda_items.select_related("owner"))
    mentioned = Role.objects.in_bulk({
        int(match[2]) for item in items for match in MENTION.finditer(item.outcome)
    })
    leads = {}
    for assignment in (
        Assignment.objects
        .current()
        .filter(role__in=mentioned.values())
        .select_related("user")
        .order_by("user__full_name", "user__email")
    ):
        leads.setdefault(assignment.role_id, []).append(person(assignment.user))

    def roles(item):
        ids = dict.fromkeys(int(match[2]) for match in MENTION.finditer(item.outcome))
        return [
            {
                "id": role.pk,
                "name": role.name,
                "circle_id": role.circle_id,
                "archived": role.archived_on is not None,
                "role_leads": leads.get(role.pk, []),
                "url": absolute(role),
            }
            for role in (mentioned.get(id) for id in ids)
            if role
        ]

    invited = list(meeting.invited_roles.order_by("name"))
    outputs = meeting_outputs(meeting)
    return summary(meeting, sum(1 for item in items if item.outcome or item.link)) | {
        "secretary": str(meeting.secretary) if meeting.secretary else None,
        "attendees": [
            person(user) for user in meeting.attendees.order_by("full_name", "email")
        ],
        "invited_roles": [
            {"id": role.pk, "title": role.name, "url": absolute(role)}
            for role in invited
        ],
        "items": [
            {
                "id": item.pk,
                "label": item.label or str(item),
                "owner": person(item.owner),
                "outcome": item.outcome,
                "outcome_plain": plain_mentions(item.outcome),
                "roles": roles(item),
                "link": item.link,
                "proposal_id": item.proposal_id,
                "is_completed": item.is_completed,
            }
            for item in items
        ],
        # Like the progress updates of tactical meetings
        "links": [
            {
                "id": link.pk,
                "role_id": link.role_id,
                "role": link.role.name,
                "title": link.title,
                "url": link.url,
                "description": link.description,
            }
            for link in meeting.progress_links()
        ],
        "adopted": [
            {
                "id": entry["proposal"].pk,
                "title": str(entry["proposal"]),
                "url": absolute(entry["proposal"]),
            }
            for entry in outputs["proposals"]
        ],
        "withdrawn": [
            {"id": proposal.pk, "title": str(proposal), "url": absolute(proposal)}
            for proposal in outputs["withdrawn"]
        ],
        "elections": [
            {
                "role_id": election.role_id,
                "role": election.role.name,
                "person": str(election.user) if election.user else None,
                "term_ends_on": election.term_ends_on.isoformat()
                if election.term_ends_on
                else None,
            }
            for election in outputs["elections"]
        ],
        "minutes": meeting.minutes,
    }
