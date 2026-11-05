from urllib.parse import urlencode

from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import Truncator
from django.utils.translation import gettext, gettext_lazy as _
from django.views.decorators.http import require_POST

from governance.accounts.models import User
from governance.forms import ModelForm
from governance.meetings.access import can_add_items, can_run
from governance.meetings.activity import end_inactive_meetings, end_meeting
from governance.meetings.elections import ElectionForm
from governance.meetings.models import (
    STEP_CHOICES,
    TACTICAL_STEP_CHOICES,
    AgendaItem,
    Meeting,
)
from governance.meetings.outputs import meeting_outputs
from governance.proposals.drafting import can_edit
from governance.proposals.instructions import consequences, problems
from governance.proposals.models import Proposal, Response
from governance.proposals.process import current_responses
from governance.proposals.views import annotate_changes, drafting_context
from governance.roles.constitution import FACILITATOR, LEAD, SECRETARY
from governance.roles.models import Assignment, ChecklistItem, Metric, Role
from governance.roles.permissions import can_start_meeting, members, proposer_roles


def holder(circle, core_role):
    assignment = (
        Assignment.objects
        .current()
        .filter(role__circle=circle, role__core_role=core_role, role__archived_on=None)
        .select_related("user")
        .first()
    )
    return assignment.user if assignment else None


def meeting_list(request, pk):
    circle = get_object_or_404(Role.objects.circles(), pk=pk)
    meetings = circle.meetings.all()
    if kind := request.GET.get("kind"):
        meetings = meetings.filter(kind=kind)
    return render(
        request,
        "meetings/meeting_list.html",
        {
            "circle": circle,
            "ancestors": [*circle.ancestors(), circle],
            "page": Paginator(meetings, 50).get_page(request.GET.get("page")),
            "can_start_meeting": can_start_meeting(request.user, circle),
        },
    )


def meeting_detail(request, pk):
    meeting = get_object_or_404(
        Meeting.objects.select_related("circle", "facilitator", "secretary"), pk=pk
    )
    return render(
        request,
        "meetings/meeting_detail.html",
        agenda_context(request, meeting)
        | {
            "ancestors": [*meeting.circle.ancestors(), meeting.circle]
            if meeting.circle
            else [],
            "proposals": meeting.proposals.select_related("proposer"),
            # The summary once the meeting ended
            "outputs": meeting_outputs(meeting) if meeting.ended_at else None,
            "elections": meeting.elections.select_related("role", "user"),
            "attendees": meeting.attendees.order_by("full_name", "email"),
            "invitable": User.objects
            .active()
            .exclude(pk__in=meeting.attendees.values("pk"))
            .order_by("full_name", "email"),
            "election_form": ElectionForm(meeting=meeting)
            if meeting.kind == Meeting.GOVERNANCE
            and meeting.is_running
            and can_run(request.user, meeting)
            else None,
        }
        | current_context(request, meeting)
        | tactical_context(meeting),
    )


def tactical_context(meeting):
    """Checklists and metrics of the invited roles (and the circle's own)"""
    if meeting.kind != Meeting.TACTICAL:
        return {}
    # A sub-circle's own items are reported in the sub-circle's meetings,
    # not in those of the circle containing it
    roles = list(meeting.invited_roles.filter(is_circle=False))
    if meeting.circle:
        roles.append(meeting.circle)
    return {
        "tactical_steps": TACTICAL_STEP_CHOICES,
        "invited_roles": meeting.invited_roles.select_related("circle").order_by(
            "circle__name", "position", "name"
        ),
        "checklist_items": ChecklistItem.objects
        .filter(role__in=roles)
        .select_related("role")
        .order_by("role__name", "position"),
        "metrics": Metric.objects
        .filter(role__in=roles)
        .select_related("role")
        .order_by("role__name", "position"),
    }


def current_context(request, meeting):
    """The agenda item being processed"""
    item = meeting.current_item
    if item is None or not meeting.is_running:
        return {}
    context = {"current": item, "steps": STEP_CHOICES}
    if proposal := item.proposal:
        context |= {
            "changes": annotate_changes(proposal),
            "objections": proposal.objections.select_related("user", "role"),
            # Who may object for which role (constitution 5.3)
            "objectors": [
                (f"{member.pk}:{role.pk}", f"{member} – {role}")
                for member in members(meeting.circle)
                for role in proposer_roles(member, meeting.circle)
            ],
            # Concerns of the members who requested the meeting
            "concerns": current_responses(proposal)
            .filter(kind__in=[Response.MEETING, Response.OBJECTION])
            .exclude(text="")
            .select_related("user"),
        }
        if can_edit(request.user, proposal):
            # The secretary amends the proposal in the meeting
            context |= drafting_context(proposal) | {
                "can_amend": True,
                "next_query": "?" + urlencode({"next": meeting.get_absolute_url()}),
            }
        elif proposal.instructions and proposal.status != Proposal.ADOPTED:
            # Conflicts, e.g. with a proposal adopted earlier in the
            # meeting, and circles turning back into roles are shown before
            # adopting, to everybody
            context["problems"] = problems(proposal)
            context["reverting"] = consequences(proposal)
    return context


def runnable_meeting(request, pk):
    meeting = get_object_or_404(Meeting.objects.select_related("circle"), pk=pk)
    if not can_run(request.user, meeting):
        raise PermissionDenied
    return meeting


@require_POST
def meeting_create(request, pk):
    circle = get_object_or_404(Role.objects.active().circles(), pk=pk)
    if not can_start_meeting(request.user, circle):
        raise PermissionDenied
    kind = (
        Meeting.TACTICAL
        if request.POST.get("kind") == Meeting.TACTICAL
        else Meeting.GOVERNANCE
    )
    # One meeting at a time per circle: starting another one joins it,
    # unless it has been inactive for hours
    end_inactive_meetings(circle.meetings.all())
    if running := circle.meetings.running().first():
        return redirect(running)
    # Calling a meeting starts it, the agenda is built in the meeting
    meeting = Meeting.objects.create(
        circle=circle,
        kind=kind,
        started_at=timezone.now(),
        called_by=request.user if kind == Meeting.TACTICAL else None,
        # Stand-ins for unfilled roles, in the constitution's order (5.3.6)
        facilitator=holder(circle, FACILITATOR)
        or holder(circle, SECRETARY)
        or holder(circle, LEAD)
        or request.user,
        secretary=holder(circle, SECRETARY)
        or holder(circle, FACILITATOR)
        or holder(circle, LEAD)
        or request.user,
    )
    meeting.attendees.set(members(circle))
    if kind == Meeting.TACTICAL:
        # The circle's regular tactical meetings invite all its roles
        meeting.invited_roles.set(circle.roles.active())
    return redirect(meeting)


class TacticalMeetingForm(ModelForm):
    class Meta:
        model = Meeting
        fields = ["invited_roles"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields["invited_roles"]
        field.required = True
        field.queryset = (
            Role.objects
            .active()
            .exclude(circle=None)
            .select_related("circle")
            .order_by("circle__name", "position", "name")
        )
        field.label_from_instance = lambda role: f"{role} ({role.circle})"
        field.widget.attrs["size"] = 15
        field.help_text = _(
            "Any partner may call a tactical meeting and invite the roles"
            " they need. Hold Ctrl or Cmd to select several."
        )


def tactical_call(request):
    """An ad-hoc tactical meeting, called by anybody"""
    initial = {"invited_roles": request.GET.getlist("role")}
    form = TacticalMeetingForm(request.POST or None, initial=initial)
    if form.is_valid():
        meeting = form.save(commit=False)
        meeting.kind = Meeting.TACTICAL
        meeting.called_by = meeting.facilitator = request.user
        meeting.started_at = timezone.now()
        meeting.save()
        form.save_m2m()
        meeting.attendees.set(
            User.objects.active().filter(
                Q(pk=request.user.pk)
                | Q(
                    pk__in=Assignment.objects
                    .current()
                    .filter(role__in=meeting.invited_roles.all())
                    .values("user")
                )
            )
        )
        return redirect(meeting)
    return render(
        request,
        "generic/object_form.html",
        {
            "title": gettext("Call a tactical meeting"),
            "form": form,
            "cancel_url": request.headers.get("referer") or "/",
        },
    )


@require_POST
def meeting_step(request, pk):
    """The step of a meeting: the rounds around the agenda"""
    meeting = runnable_meeting(request, pk)
    if request.POST.get("step") in dict(meeting.steps):
        meeting.step = request.POST["step"]
        meeting.save(update_fields=["step"])
    return redirect(meeting)


@require_POST
def meeting_attendees(request, pk):
    """Inviting somebody, or removing them from the attendees"""
    meeting = runnable_meeting(request, pk)
    user = get_object_or_404(User.objects.active(), pk=request.POST.get("user"))
    if request.POST.get("action") == "remove":
        meeting.attendees.remove(user)
    else:
        meeting.attendees.add(user)
    return redirect(meeting)


class MeetingForm(ModelForm):
    class Meta:
        model = Meeting
        fields = ["facilitator", "secretary", "minutes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Usually the Facilitator and the Secretary, or somebody standing in
        for field in ["facilitator", "secretary"]:
            self.fields[field].queryset = User.objects.active()


def meeting_update(request, pk):
    meeting = runnable_meeting(request, pk)
    form = MeetingForm(request.POST or None, instance=meeting)
    if form.is_valid():
        form.save()
        return redirect(meeting)
    return render(
        request,
        "generic/object_form.html",
        {
            "title": gettext("Edit %(meeting)s") % {"meeting": meeting},
            "form": form,
            "cancel_url": meeting.get_absolute_url(),
        },
    )


@require_POST
def meeting_end(request, pk):
    meeting = runnable_meeting(request, pk)
    if meeting.is_running:
        end_meeting(meeting)
    return redirect(meeting)


# Agenda ######################################################################


def agenda_context(request, meeting):
    circle = meeting.circle
    runs = can_run(request.user, meeting)
    can_add = can_add_items(request.user, meeting)
    items = list(meeting.agenda_items.select_related("owner", "proposal"))
    for item in items:
        item.can_remove = (
            can_add
            and (runs or item.owner_id == request.user.pk)
            and not item.is_completed
        )
    context = {
        "meeting": meeting,
        "agenda": items,
        "can_run": runs,
        "can_add_items": can_add,
    }
    if can_add and meeting.kind == Meeting.GOVERNANCE:
        on_agenda = [item.proposal_id for item in items if item.proposal_id]
        context["addable_proposals"] = (
            Proposal.objects
            .filter(circle=circle)
            .filter(
                Q(status=Proposal.IN_MEETING)
                # Async proposals too: like requesting a meeting (5.3)
                | Q(status=Proposal.PUBLISHED)
                | Q(status=Proposal.DRAFT, proposer=request.user)
            )
            .exclude(pk__in=on_agenda)
            .order_by("status", "-created_at")
        )
    return context


@require_POST
def agenda_add(request, pk):
    meeting = get_object_or_404(Meeting.objects.select_related("circle"), pk=pk)
    context = agenda_context(request, meeting)
    if not context["can_add_items"]:
        raise PermissionDenied
    position = max((item.position for item in context["agenda"]), default=0) + 1
    if proposal_id := request.POST.get("proposal"):
        if "addable_proposals" not in context:
            raise PermissionDenied  # Tactical meetings don't process proposals
        proposal = get_object_or_404(context["addable_proposals"], pk=proposal_id)
        if proposal.status in {Proposal.DRAFT, Proposal.PUBLISHED}:
            # Brought into the meeting: a draft isn't private anymore, an
            # async proposal's acceptance period ends
            proposal.status = Proposal.IN_MEETING
        proposal.meeting = meeting
        proposal.save(update_fields=["status", "meeting"])
        AgendaItem.objects.create(
            meeting=meeting,
            position=position,
            owner=request.user,
            proposal=proposal,
            label=Truncator(str(proposal)).chars(500),
        )
    elif label := request.POST.get("label", "").strip():
        AgendaItem.objects.create(
            meeting=meeting, position=position, owner=request.user, label=label[:500]
        )
    return redirect(meeting)


@require_POST
def agenda_remove(request, pk):
    item = get_object_or_404(
        AgendaItem.objects.select_related("meeting__circle"), pk=pk
    )
    context = agenda_context(request, item.meeting)
    if not next((i.can_remove for i in context["agenda"] if i.pk == item.pk), False):
        raise PermissionDenied
    item.delete()
    return redirect(item.meeting)


@require_POST
def agenda_move(request, pk):
    """Moves an agenda item up or down"""
    item = get_object_or_404(
        AgendaItem.objects.select_related("meeting__circle"), pk=pk
    )
    meeting = item.meeting
    if not can_run(request.user, meeting):
        raise PermissionDenied
    items = list(meeting.agenda_items.all())
    index = items.index(item)
    other = index + (-1 if request.POST.get("direction") == "up" else 1)
    if 0 <= other < len(items):
        items[index], items[other] = items[other], items[index]
        for position, agenda_item in enumerate(items, 1):
            if agenda_item.position != position:
                agenda_item.position = position
                agenda_item.save(update_fields=["position"])
    return redirect(meeting)
