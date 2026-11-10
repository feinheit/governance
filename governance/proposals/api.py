"""Proposals through the API, e.g. prepared from a tension with an LLM

Circle members create drafts and change and publish their own drafts, and
respond to published proposals like on their pages; nothing else: the
secretary amends others' proposals only in the page of a running meeting. The server checks the instructions and returns the
conflicts and errors it finds.
"""

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Router, Schema, Status
from ninja.errors import HttpError

from governance.proposals import process
from governance.proposals.describe import describe
from governance.proposals.instructions import (
    ProposalError,
    names_for,
    problems,
    validate_format,
)
from governance.proposals.models import Proposal
from governance.proposals.views import ResponseForm
from governance.roles.models import Role
from governance.roles.permissions import is_member, proposer_roles


router = Router(tags=["proposals"])


class ProposalIn(Schema):
    circle_id: int
    # One of the proposer's roles in the circle
    role_id: int
    tension: str
    instructions: list = []


class ResponseIn(Schema):
    # consent ("no objection"), meeting ("discuss in a meeting") or comment
    kind: str
    text: str = ""


class ProposalPatch(Schema):
    tension: str | None = None
    instructions: list | None = None


class ChangeOut(Schema):
    """A readable change like on the proposal's page"""

    action: str
    label: str
    subject: str
    old: str
    new: str
    details: list[tuple[str, str]]


class ResponseOut(Schema):
    user: str
    kind: str
    label: str
    text: str
    created_at: str


class ResponsesOut(Schema):
    """Like the proposal page: consents and meeting requests only counted,
    questions and concerns with their author"""

    consents: int
    meeting_requests: int
    others: int
    entries: list[ResponseOut]


class ProposalOut(Schema):
    id: int
    circle_id: int
    circle: str
    proposer: str | None
    role_id: int | None
    status: str
    title: str
    tension: str
    instructions: list
    names: dict
    changes: list[ChangeOut]
    created_at: str
    published_at: str | None
    deadline: str | None
    # The day the hourly task adopts it, like the pages show it
    adopted_on: str | None
    decided_at: str | None
    url: str
    problems: list[str]
    responses: ResponsesOut | None
    # The user's current position on a published proposal: consent or
    # meeting, None without one (or not published)
    my_response: str | None


class ProblemsOut(Schema):
    problems: list[str]


def own_draft(user, proposal):
    """What the API changes: the user's own drafts. The secretary amends
    proposals in a running meeting's page only, not through scripts."""
    return proposal.status == Proposal.DRAFT and proposal.proposer_id == user.pk


def _iso(value):
    """In local time: the first ten characters are the day the pages show"""
    return timezone.localtime(value).isoformat() if value else None


def out(request, proposal):
    return {
        "id": proposal.pk,
        "circle_id": proposal.circle_id,
        "circle": str(proposal.circle),
        "proposer": str(proposal.proposer) if proposal.proposer else None,
        "role_id": proposal.role_id,
        "status": proposal.status,
        "title": str(proposal),
        "tension": proposal.tension,
        "instructions": proposal.instructions,
        "names": proposal.names,
        "changes": [
            {
                "action": change.action,
                "label": str(change.label),
                "subject": change.subject,
                "old": change.old if isinstance(change.old, str) else "",
                "new": change.new if isinstance(change.new, str) else "",
                "details": [(str(label), str(text)) for label, text in change.details],
            }
            for change in describe(proposal.instructions, proposal.names)
        ],
        "created_at": _iso(proposal.created_at),
        "published_at": _iso(proposal.published_at),
        "deadline": _iso(proposal.deadline),
        "adopted_on": proposal.adopted_on and proposal.adopted_on.isoformat(),
        "decided_at": _iso(proposal.decided_at),
        "url": settings.BASE_URL + proposal.get_absolute_url(),
        "problems": problems(proposal)
        if own_draft(request.user, proposal) and proposal.instructions
        else [],
        "responses": responses_out(proposal),
        "my_response": my_response(request.user, proposal),
    }


def my_response(user, proposal):
    if proposal.status != Proposal.PUBLISHED:
        return None
    position = process.positions(proposal).get(user.pk)
    return position.kind if position else None


def responses_out(proposal):
    if proposal.status not in {Proposal.PUBLISHED, Proposal.IN_MEETING}:
        return None
    summary = process.response_summary(proposal)
    return {
        "consents": summary["consents"],
        "meeting_requests": summary["meeting_requests"],
        "others": summary["others"],
        "entries": [
            {
                "user": str(response.user),
                "kind": response.kind,
                "label": str(response.get_kind_display()),
                "text": response.text,
                "created_at": _iso(response.created_at),
            }
            for response in summary["responses"]
        ],
    }


def set_instructions(proposal, instructions):
    if found := validate_format(instructions):
        raise HttpError(400, " ".join(found))
    proposal.instructions = instructions
    proposal.names = names_for(instructions)


@router.get("proposals/", response=list[ProposalOut])
def proposal_list(
    request,
    circle_id: int | None = None,
    status: str | None = None,
    *,
    open: bool = False,
):
    """Proposals, without the drafts of others; the newest first. ``open``:
    the published ones of the user's circles, open for their response, the
    nearest deadline first"""
    proposals = Proposal.objects.visible_to(request.user).select_related(
        "circle", "proposer"
    )
    if circle_id:
        proposals = proposals.filter(circle_id=circle_id)
    if status:
        proposals = proposals.filter(status=status)
    if open:
        proposals = [
            proposal
            for proposal in proposals.filter(status=Proposal.PUBLISHED).order_by(
                "deadline", "pk"
            )
            if is_member(request.user, proposal.circle)
        ]
    return [out(request, proposal) for proposal in proposals[:100]]


@router.get("proposals/{int:pk}/", response=ProposalOut)
def proposal_detail(request, pk: int):
    proposal = get_object_or_404(Proposal.objects.visible_to(request.user), pk=pk)
    return out(request, proposal)


@router.post("proposals/", response=ProposalOut)
def proposal_create(request, data: ProposalIn):
    """A draft; ``problems`` lists what would prevent adopting it"""
    circle = get_object_or_404(Role.objects.active().with_inside(), pk=data.circle_id)
    role = proposer_roles(request.user, circle).filter(pk=data.role_id).first()
    if role is None:
        raise HttpError(403, "Propose from one of your roles in the circle.")
    proposal = Proposal(
        circle=circle,
        role=role,
        proposer=request.user,
        tension=data.tension.strip(),
        created_at=timezone.now(),
    )
    set_instructions(proposal, data.instructions)
    proposal.save()
    return out(request, proposal)


@router.patch("proposals/{int:pk}/", response=ProposalOut)
def proposal_update(request, pk: int, data: ProposalPatch):
    proposal = get_object_or_404(Proposal.objects.visible_to(request.user), pk=pk)
    if not own_draft(request.user, proposal):
        raise HttpError(403, "Only the proposer changes a draft.")
    if data.tension is not None:
        proposal.tension = data.tension.strip()
    if data.instructions is not None:
        set_instructions(proposal, data.instructions)
    proposal.save()
    return out(request, proposal)


@router.post(
    "proposals/{int:pk}/publish/", response={200: ProposalOut, 400: ProblemsOut}
)
def proposal_publish(request, pk: int):
    """Publishes the draft for the async process"""
    proposal = get_object_or_404(
        Proposal.objects.visible_to(request.user), pk=pk, status=Proposal.DRAFT
    )
    if proposal.proposer != request.user:
        raise HttpError(403, "Only the proposer publishes a draft.")
    try:
        process.publish(proposal)
    except ProposalError as exc:
        return Status(400, {"problems": exc.problems})
    return out(request, proposal)


@router.post(
    "proposals/{int:pk}/responses/", response={200: ProposalOut, 400: ProblemsOut}
)
def proposal_respond(request, pk: int, data: ResponseIn):
    """A response like on the proposal's page: no objection, discuss in a
    meeting (with the concern, optional) or a question or comment"""
    proposal = get_object_or_404(
        Proposal.objects.filter(status__in=[Proposal.PUBLISHED, Proposal.IN_MEETING]),
        pk=pk,
    )
    if not is_member(request.user, proposal.circle):
        raise HttpError(403, "Only the circle's members respond.")
    form = ResponseForm(
        {"kind": data.kind, "text": data.text},
        is_open=proposal.status == Proposal.PUBLISHED,
        is_proposer=proposal.proposer_id == request.user.pk,
    )
    if not form.is_valid():
        return Status(
            400,
            {"problems": [str(e) for errors in form.errors.values() for e in errors]},
        )
    try:
        process.respond(
            proposal, request.user, form.cleaned_data["kind"], form.cleaned_data["text"]
        )
    except ProposalError as exc:
        return Status(400, {"problems": exc.problems})
    proposal.refresh_from_db()
    return out(request, proposal)
