"""Processing the agenda of a governance meeting, see section 4 of SPEC.md

The facilitator and the secretary go through the steps of integrative
decision-making; the app guides them but doesn't enforce the steps. The
secretary amends the proposal (``drafting.can_edit``), objections are
recorded with the facilitator's test. Adopting needs every objection
tested and every valid one integrated.
"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.translation import gettext
from django.views.decorators.http import require_POST

from governance.accounts.models import User
from governance.meetings.access import can_run
from governance.meetings.models import STEP_CHOICES, AgendaItem, Meeting, Objection
from governance.proposals.instructions import ProposalError, adopt
from governance.proposals.models import Proposal
from governance.proposals.process import check_role
from governance.roles.permissions import proposer_roles


STEPS = [key for key, _label in STEP_CHOICES]


def running_item(request, pk):
    """An agenda item of a running meeting, for its facilitator or secretary"""
    item = get_object_or_404(
        AgendaItem.objects.select_related("meeting__circle", "proposal"), pk=pk
    )
    meeting = item.meeting
    if not meeting.is_running or not can_run(request.user, meeting):
        raise PermissionDenied
    return item


@require_POST
def item_process(request, pk):
    """Makes the item the current one"""
    item = running_item(request, pk)
    item.meeting.current_item = item
    item.meeting.save(update_fields=["current_item"])
    if item.proposal and not item.step:
        item.step = STEPS[0]
        item.save(update_fields=["step"])
    return redirect(item.meeting)


@require_POST
def item_step(request, pk):
    item = running_item(request, pk)
    if (step := request.POST.get("step")) in STEPS:
        item.step = step
        item.save(update_fields=["step"])
    return redirect(item.meeting)


def complete(item):
    item.is_completed = True
    item.save(update_fields=["is_completed"])
    meeting = item.meeting
    if meeting.current_item_id == item.pk:
        meeting.current_item = None
        meeting.save(update_fields=["current_item"])


@require_POST
def item_complete(request, pk):
    item = running_item(request, pk)
    complete(item)
    return redirect(item.meeting)


@require_POST
def item_to_proposal(request, pk):
    """An agenda item's tension becomes a proposal, amended by the secretary"""
    item = running_item(request, pk)
    if item.proposal:
        return redirect(item.meeting)
    with transaction.atomic():
        proposer = item.owner or request.user
        item.proposal = Proposal.objects.create(
            circle=item.meeting.circle,
            proposer=proposer,
            # The secretary changes it in the tension form if needed
            role=proposer_roles(proposer, item.meeting.circle).first(),
            tension=item.label,
            status=Proposal.IN_MEETING,
            meeting=item.meeting,
            created_at=timezone.now(),
        )
        item.step = STEPS[0]
        item.save(update_fields=["proposal", "step"])
    # Amended right here, in the meeting
    return redirect(item.meeting)


@require_POST
def objection_add(request, pk):
    item = running_item(request, pk)
    # "user:role": objections are raised for a role the objector represents
    user_id, _sep, role_id = request.POST.get("objector", "").partition(":")
    user = User.objects.active().filter(pk=user_id or None).first()
    role = (
        proposer_roles(user, item.meeting.circle).filter(pk=role_id or None).first()
        if user
        else None
    )
    text = request.POST.get("text", "").strip()
    if item.proposal and user and role and text:
        Objection.objects.create(
            proposal=item.proposal,
            meeting=item.meeting,
            user=user,
            role=role,
            text=text,
        )
        if item.step != "integration":
            item.step = "objections"
            item.save(update_fields=["step"])
    else:
        messages.error(request, gettext("Who objects, and why?"))
    return redirect(item.meeting)


@require_POST
def objection_update(request, pk):
    """The facilitator's test, and integrating the objection"""
    objection = get_object_or_404(Objection, pk=pk)
    # In the meeting processing the proposal now: an objection left open
    # when a meeting ended is tested in the next one
    item = AgendaItem.objects.filter(
        proposal=objection.proposal, meeting__in=Meeting.objects.running()
    ).first()
    if item is None:
        raise PermissionDenied
    item = running_item(request, item.pk)
    action = request.POST.get("action")
    if action in {"valid", "invalid"}:
        objection.is_valid = action == "valid"
    elif action == "integrated":
        objection.is_integrated = True
    objection.save(update_fields=["is_valid", "is_integrated"])
    if objection.is_valid and not objection.is_integrated:
        item.step = "integration"
        item.save(update_fields=["step"])
    return redirect(item.meeting)


@require_POST
def item_adopt(request, pk):
    item = running_item(request, pk)
    proposal = item.proposal
    if proposal is None or proposal.status == Proposal.ADOPTED:
        raise PermissionDenied
    if any(objection.is_open for objection in proposal.objections.all()):
        messages.error(
            request,
            gettext("Test every objection first and integrate the valid ones."),
        )
        return redirect(item.meeting)
    try:
        with transaction.atomic():
            # Proposals come from roles, also those of guests (5.3.1)
            check_role(proposal)
            proposal.meeting = item.meeting
            adopt(proposal)
            complete(item)
    except ProposalError as exc:
        for problem in exc.problems:
            messages.error(request, problem)
    else:
        messages.success(request, gettext("The proposal is adopted."))
    return redirect(item.meeting)


@require_POST
def item_outcome(request, pk):
    """The outcome of a tension in a tactical meeting"""
    item = running_item(request, pk)
    item.outcome = request.POST.get("outcome", "").strip()
    link = request.POST.get("link", "").strip()
    if link and not link.startswith(("https://", "http://")):
        messages.error(request, gettext("The link has to start with https://."))
        return redirect(item.meeting)
    item.link = link[:1000]
    item.save(update_fields=["outcome", "link"])
    complete(item)
    return redirect(item.meeting)
