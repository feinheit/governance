"""Proposals through the API, e.g. prepared from a tension with an LLM

Circle members create drafts and change and publish their own drafts,
nothing else: the secretary amends others' proposals only in the page of a
running meeting. The server checks the instructions and returns the
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
from governance.roles.models import Role
from governance.roles.permissions import proposer_roles


router = Router(tags=["proposals"])


class ProposalIn(Schema):
    circle_id: int
    # One of the proposer's roles in the circle
    role_id: int
    tension: str
    instructions: list = []


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


class ProposalOut(Schema):
    id: int
    circle_id: int
    circle: str
    proposer: str | None
    role_id: int | None
    status: str
    kind: str
    title: str
    tension: str
    instructions: list
    names: dict
    changes: list[ChangeOut]
    created_at: str
    published_at: str | None
    deadline: str | None
    decided_at: str | None
    url: str
    problems: list[str]


class ProblemsOut(Schema):
    problems: list[str]


def own_draft(user, proposal):
    """What the API changes: the user's own drafts. The secretary amends
    proposals in a running meeting's page only, not through scripts."""
    return proposal.status == Proposal.DRAFT and proposal.proposer_id == user.pk


def _iso(value):
    return value.isoformat() if value else None


def out(request, proposal):
    return {
        "id": proposal.pk,
        "circle_id": proposal.circle_id,
        "circle": str(proposal.circle),
        "proposer": str(proposal.proposer) if proposal.proposer else None,
        "role_id": proposal.role_id,
        "status": proposal.status,
        "kind": proposal.kind,
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
        "created_at": proposal.created_at.isoformat(),
        "published_at": _iso(proposal.published_at),
        "deadline": _iso(proposal.deadline),
        "decided_at": _iso(proposal.decided_at),
        "url": settings.BASE_URL + proposal.get_absolute_url(),
        "problems": problems(proposal)
        if own_draft(request.user, proposal) and proposal.instructions
        else [],
    }


def set_instructions(proposal, instructions):
    if found := validate_format(instructions):
        raise HttpError(400, " ".join(found))
    proposal.instructions = instructions
    proposal.names = names_for(instructions)


@router.get("proposals/", response=list[ProposalOut])
def proposal_list(request, circle_id: int | None = None, status: str | None = None):
    """Proposals, without the drafts of others; the newest first"""
    proposals = Proposal.objects.visible_to(request.user).select_related(
        "circle", "proposer"
    )
    if circle_id:
        proposals = proposals.filter(circle_id=circle_id)
    if status:
        proposals = proposals.filter(status=status)
    return [out(request, proposal) for proposal in proposals[:100]]


@router.get("proposals/{int:pk}/", response=ProposalOut)
def proposal_detail(request, pk: int):
    proposal = get_object_or_404(Proposal.objects.visible_to(request.user), pk=pk)
    return out(request, proposal)


@router.post("proposals/", response=ProposalOut)
def proposal_create(request, data: ProposalIn):
    """A draft; ``problems`` lists what would prevent adopting it"""
    circle = get_object_or_404(Role.objects.active().circles(), pk=data.circle_id)
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
