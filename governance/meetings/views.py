from urllib.parse import urlencode

from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import Truncator
from django.utils.translation import gettext, gettext_lazy as _, ngettext
from django.views.decorators.http import require_POST

from governance.accounts.models import User
from governance.forms import ModelForm
from governance.meetings.access import (
    autosaving,
    can_add_items,
    can_run,
    can_take_over,
)
from governance.meetings.activity import end_inactive_meetings, end_meeting
from governance.meetings.elections import ElectionForm
from governance.meetings.models import (
    STEP_CHOICES,
    TACTICAL_STEP_CHOICES,
    AgendaItem,
    Meeting,
)
from governance.meetings.outputs import meeting_outputs
from governance.modals import is_modal
from governance.proposals.describe import summarize
from governance.proposals.drafting import can_edit
from governance.proposals.instructions import consequences, problems
from governance.proposals.models import Proposal, Response
from governance.proposals.process import current_responses
from governance.proposals.views import annotate_changes, drafting_context
from governance.roles.models import Assignment, ChecklistItem, Link, Metric, Role
from governance.roles.permissions import (
    acting_secretaries,
    asks_before_starting,
    can_start_meeting,
    members,
    proposer_roles,
)


def meeting_list(request, pk):
    circle = get_object_or_404(Role.objects.with_inside(), pk=pk)
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
            "asks_before_starting": asks_before_starting(request.user, circle),
            # One meeting at a time per circle
            "running_meeting": circle.meetings.running().first(),
        },
    )


def meeting_detail(request, pk):
    meeting = get_object_or_404(
        Meeting.objects.select_related("circle", "secretary"), pk=pk
    )
    # Following, people look at another review on their own screen
    # (?step=, which the page's updates keep), the meeting stays there
    shown_step = meeting.step
    if (
        meeting.is_running
        and meeting.kind == Meeting.TACTICAL
        and request.GET.get("step") in REVIEW_STEPS
    ):
        shown_step = request.GET["step"]
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
            # Others taking over as the meeting's secretary are asked first
            "is_acting_secretary": not meeting.circle
            or acting_secretaries(meeting.circle).filter(pk=request.user.pk).exists(),
            "shown_step": shown_step,
            "review_steps": REVIEW_STEPS,
            "election_form": ElectionForm(meeting=meeting)
            if meeting.kind == Meeting.GOVERNANCE
            and meeting.is_running
            and can_run(request.user, meeting)
            else None,
        }
        | current_context(request, meeting)
        | tactical_context(
            meeting, step=shown_step, earlier=request.GET.get("earlier")
        ),
    )


# The tactical meetings whose outcomes the progress updates show: three,
# "Show earlier meetings" ten, then ten more each time
EARLIER_MEETINGS = 3
MORE_EARLIER_MEETINGS = 10
MAX_EARLIER_MEETINGS = 200


# The tactical steps with something to show, which followers look at
REVIEW_STEPS = {"checklists", "metrics", "progress"}


def tactical_context(meeting, *, step, earlier=None):
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
    } | (progress_context(meeting, roles, earlier) if step == "progress" else {})


def progress_context(meeting, roles, count):
    """Progress updates: where the projects are (the links of the circle and
    the invited roles), and the outcomes of the circle's last tactical
    meetings with outcomes or links to check on (``count`` of them)"""
    try:
        count = min(max(int(count), EARLIER_MEETINGS), MAX_EARLIER_MEETINGS)
    except TypeError, ValueError:
        count = EARLIER_MEETINGS
    meetings = (
        Meeting.objects
        .filter(circle=meeting.circle, kind=Meeting.TACTICAL)
        .exclude(ended_at=None)
        .exclude(pk=meeting.pk)
        .filter(
            pk__in=AgendaItem.objects.exclude(outcome="", link="").values("meeting")
        )
        .order_by("-started_at")
        if meeting.circle
        else Meeting.objects.none()
    )
    earlier = list(meetings[: count + 1])
    more = None
    if len(earlier) > count:
        # From three right to ten, then ten more each time
        more = (count if count >= MORE_EARLIER_MEETINGS else 0) + MORE_EARLIER_MEETINGS
    return {
        "earlier_more": more,
        "progress_links": Link.objects
        .filter(role__in=roles)
        .select_related("role")
        .order_by("role__name", "position"),
        "earlier_outcomes": AgendaItem.objects
        .filter(meeting__in=earlier[:count])
        .exclude(outcome="", link="")
        .select_related("meeting")
        .order_by("-meeting__started_at", "position"),
    }


def current_context(request, meeting):
    """The agenda item being processed"""
    item = meeting.current_item
    if item is None or not meeting.is_running:
        return {}
    context = {"current": item, "steps": STEP_CHOICES}
    if proposal := item.proposal:
        changes = annotate_changes(proposal)
        context |= {
            "changes": changes,
            # What it proposes now, while the secretary amends it
            "summary": summarize(changes),
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
            context["consequences"] = consequences(proposal)
    return context


def runnable_meeting(request, pk, *, running=True):
    """A meeting the user runs; changes only while it runs, after its end
    (and its mail) it stays as it was"""
    meeting = get_object_or_404(Meeting.objects.select_related("circle"), pk=pk)
    if not can_run(request.user, meeting):
        raise PermissionDenied
    if running and not meeting.is_running:
        raise PermissionDenied
    return meeting


def meeting_create(request, pk):
    """Starting a meeting; in a role (not a circle) asked first: rarely
    what people want (meetings/meeting_confirm.html)"""
    circle = get_object_or_404(Role.objects.active().with_inside(), pk=pk)
    if not (right := can_start_meeting(request.user, circle)):
        raise PermissionDenied
    if request.method != "POST":
        # Asked first (asks_before_starting()), e.g. in a modal
        return render(
            request,
            "meetings/meeting_confirm.html",
            {
                "role": circle,
                "right": right,
                "tactical": request.GET.get("kind") == Meeting.TACTICAL
                and circle.is_circle,
                "secretaries": acting_secretaries(circle).order_by("full_name", "email")
                if circle.is_circle
                else None,
            },
        )
    kind = (
        Meeting.TACTICAL
        if request.POST.get("kind") == Meeting.TACTICAL
        else Meeting.GOVERNANCE
    )
    if kind == Meeting.TACTICAL and not circle.is_circle:
        # Inside a role: governance meetings only
        raise PermissionDenied
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
        secretary=acting_secretaries(circle).order_by("pk").first() or request.user,
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
        meeting.called_by = request.user
        meeting.secretary = request.user
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


def meeting_attendees(request, pk):
    """The attendees (e.g. in a modal); the secretary invites somebody or
    removes them, the modal shows the list again"""
    if request.method == "POST":
        meeting = runnable_meeting(request, pk)
        user = get_object_or_404(User.objects.active(), pk=request.POST.get("user"))
        if request.POST.get("action") == "remove":
            meeting.attendees.remove(user)
        else:
            meeting.attendees.add(user)
        if not is_modal(request):
            return redirect(meeting)
    meeting = get_object_or_404(Meeting.objects.select_related("circle"), pk=pk)
    runs = meeting.is_running and can_run(request.user, meeting)
    return render(
        request,
        "meetings/attendees.html",
        {
            "meeting": meeting,
            "attendees": meeting.attendees.order_by("full_name", "email"),
            "can_run": runs,
            "invitable": User.objects
            .active()
            .exclude(pk__in=meeting.attendees.values("pk"))
            .order_by("full_name", "email")
            if runs
            else None,
        },
    )


class MeetingForm(ModelForm):
    class Meta:
        model = Meeting
        fields = ["minutes"]
        labels = {"minutes": _("Notes")}


def meeting_update(request, pk):
    """The meeting's notes, saved while the secretary types (autosaving())"""
    meeting = runnable_meeting(request, pk)
    form = MeetingForm(request.POST or None, instance=meeting)
    if form.is_valid():
        form.save()
        if autosaving(request):
            return HttpResponse(status=204)
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


def meeting_secretary(request, pk):
    """Somebody taking part takes over as the meeting's secretary, e.g.
    standing in for a late Secretary (5.3.6); those who aren't acting as
    the circle's Secretary are asked first (in a modal)"""
    meeting = get_object_or_404(Meeting.objects.select_related("circle"), pk=pk)
    if not (right := can_take_over(request.user, meeting)):
        raise PermissionDenied
    if request.method != "POST":
        return render(
            request,
            "generic/confirm.html",
            {
                "question": gettext("Take over as the meeting's secretary?"),
                "help": gettext("You aren't the circle's Secretary. Take over anyway?"),
                "submit_label": gettext("Take over"),
                "submit_class": "btn-primary",
                "right": right,
                "cancel_url": meeting.get_absolute_url(),
            },
        )
    if meeting.is_running:
        meeting.secretary = request.user
        meeting.save(update_fields=["secretary"])
    return redirect(meeting)


def meeting_end(request, pk):
    """Ending the meeting; with unprocessed agenda items asked first (in a
    modal)"""
    meeting = runnable_meeting(request, pk, running=False)
    if request.method != "POST":
        count = meeting.agenda_items.filter(is_completed=False).count()
        return render(
            request,
            "generic/confirm.html",
            {
                "question": gettext("End the meeting?"),
                "help": ngettext(
                    "%(count)s agenda item hasn't been processed yet, its"
                    " proposal waits for the next meeting.",
                    "%(count)s agenda items haven't been processed yet, their"
                    " proposals wait for the next meeting.",
                    count,
                )
                % {"count": count},
                "submit_label": gettext("End the meeting"),
                "submit_class": "btn-primary",
                "cancel_url": meeting.get_absolute_url(),
            },
        )
    if meeting.is_running:
        end_meeting(meeting)
    return redirect(meeting)


# Agenda ######################################################################


def agenda_context(request, meeting):
    circle = meeting.circle
    runs = can_run(request.user, meeting)
    takes_over = can_take_over(request.user, meeting)
    can_add = can_add_items(request.user, meeting)
    items = list(meeting.agenda_items.select_related("owner", "proposal"))
    for item in items:
        # The secretary processes an item by clicking its row
        item.can_process = (
            runs
            and meeting.is_running
            and not item.is_completed
            and item.pk != meeting.current_item_id
        )
        # A completed item's row leads to its result (_results.html), shown
        # while processing the tensions
        item.has_result = (
            meeting.kind == Meeting.TACTICAL
            and meeting.is_running
            and meeting.step == "tensions"
            and item.is_completed
            and bool(item.outcome or item.link)
        )
        item.can_remove = (
            can_add
            and (runs or item.owner_id == request.user.pk)
            and not item.is_completed
        )
    context = {
        "meeting": meeting,
        "agenda": items,
        # Tactical meetings stack the completed items' results (_results.html)
        "results": [item for item in items if item.has_result],
        "can_run": runs,
        "can_take_over": takes_over,
        # Ending the meeting asks first while some aren't processed
        "open_items": sum(1 for item in items if not item.is_completed),
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
        status = proposal.status
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
            proposal_status=status,
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
        AgendaItem.objects.select_related("meeting__circle", "proposal"), pk=pk
    )
    context = agenda_context(request, item.meeting)
    if not next((i.can_remove for i in context["agenda"] if i.pk == item.pk), False):
        raise PermissionDenied
    proposal = item.proposal
    if (
        proposal
        and proposal.status == Proposal.IN_MEETING
        and item.proposal_status in {Proposal.DRAFT, Proposal.PUBLISHED}
    ):
        # Back where it was: a draft stays private, an async proposal
        # continues with its deadline
        proposal.status = item.proposal_status
        proposal.meeting = None
        proposal.save(update_fields=["status", "meeting"])
    item.delete()
    return redirect(item.meeting)


@require_POST
def agenda_order(request, pk):
    """The secretary drags the agenda's items into an order (the agenda's
    drag handles, frontend/agenda.js): their IDs in the new order, missing
    ones keep their order after them"""
    meeting = runnable_meeting(request, pk)
    items = {item.pk: item for item in meeting.agenda_items.all()}
    ids = [
        int(value)
        for value in request.POST.getlist("ids")
        if value.isdigit() and int(value) in items
    ]
    order = [*dict.fromkeys(ids), *(pk for pk in items if pk not in ids)]
    for position, item_pk in enumerate(order, 1):
        if items[item_pk].position != position:
            items[item_pk].position = position
            items[item_pk].save(update_fields=["position"])
    return redirect(meeting)


@require_POST
def agenda_move(request, pk):
    """Moves an agenda item up or down"""
    item = get_object_or_404(
        AgendaItem.objects.select_related("meeting__circle"), pk=pk
    )
    meeting = item.meeting
    if not meeting.is_running or not can_run(request.user, meeting):
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
