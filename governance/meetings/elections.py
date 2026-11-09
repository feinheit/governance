"""Elections in governance meetings and their reminders, see SPEC.md"""

import datetime as dt

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.translation import gettext, gettext_lazy as _
from django.views.decorators.http import require_POST

from governance.forms import ModelForm
from governance.history.update import update_today
from governance.locking import locking_structure
from governance.meetings.access import can_run
from governance.meetings.models import Election, Meeting
from governance.notifications.role_leads import (
    announce_changes,
    role_leads_and_members,
)
from governance.roles.assignments import affected_circles, sync_circle_role_leads
from governance.roles.constitution import FACILITATOR, REP, SECRETARY
from governance.roles.models import Assignment, Role
from governance.roles.permissions import is_circle_lead, members


ELECTED = [FACILITATOR, SECRETARY, REP]
REMINDER_DAYS = 30


def elected_roles(circles):
    """Facilitator, Secretary, Circle Rep and the roles a policy makes elected"""
    return (
        Role.objects
        .active()
        .filter(circle__in=circles)
        .filter(
            Q(core_role__in=ELECTED)
            | Q(core_role="", is_circle=False, is_elected_by_policy=True)
        )
        .select_related("circle")
        .order_by("circle__name", "position")
    )


@transaction.atomic
def record_election(meeting, role, user, term_ends_on):
    """The elected person holds the role until the term ends, nobody (the
    Circle Rep only) ends its assignment; announced when the meeting ends
    (``announce_elections()``)"""
    day = timezone.localdate()
    # Recorded again in the meeting (a correction, a second vote): the
    # latest result replaces the earlier one, the role has one Role Lead
    for earlier in meeting.elections.filter(role=role):
        undo_election(earlier, day)
        earlier.delete()
    election = Election(
        meeting=meeting,
        role=role,
        user=user,
        term_ends_on=term_ends_on,
        started=user is not None,
    )
    for assignment in Assignment.objects.current().filter(role=role):
        if user and assignment.user_id == user.pk:
            election.started = False
            election.previous_term = assignment.elected_until
            assignment.elected_until = term_ends_on
            assignment.save(update_fields=["elected_until"])
        else:
            election.replaced.append({
                "pk": assignment.pk,
                "user": assignment.user_id,
                "focus": assignment.focus,
                "starts_on": assignment.starts_on and assignment.starts_on.isoformat(),
                "elected_until": assignment.elected_until
                and assignment.elected_until.isoformat(),
            })
            assignment.end(day)
    if election.started:
        Assignment.objects.create(
            role=role, user=user, starts_on=day, elected_until=term_ends_on
        )
    if role.core_role == REP:
        sync_circle_role_leads(role.circle, day)
    update_today()
    election.save()
    return election


def undo_election(election, day):
    """Reverses what recording the election changed"""
    role = election.role
    role_lead = (
        Assignment.objects.current().filter(role=role, user=election.user).first()
    )
    if role_lead and election.started:
        # Never held, also when the meeting ran past midnight meanwhile
        role_lead.delete()
    elif role_lead:
        role_lead.elected_until = election.previous_term
        role_lead.save(update_fields=["elected_until"])
    for data in election.replaced:
        if not Assignment.objects.filter(pk=data["pk"]).update(ends_on=None):
            # Removed because it started the same day
            Assignment.objects.create(
                role=role,
                user_id=data["user"],
                focus=data["focus"],
                starts_on=data["starts_on"],
                elected_until=data["elected_until"],
            )
    if role.core_role == REP:
        sync_circle_role_leads(role.circle, day)


class _Undone(Exception):
    pass


def announce_elections(meeting):
    """When the meeting ends: the people about the roles they got and lost
    in its elections, the Secretaries about people joining and leaving (a
    Circle Rep in the super-circle), the results after corrections only"""
    # Not those of roles removed meanwhile, their proposal told the Role Leads
    elections = list(
        meeting.elections
        .filter(role__archived_on=None)
        .select_related("role__circle")
        .order_by("-pk")
    )
    if not elections:
        return
    circles = {
        circle
        for election in elections
        for circle in affected_circles(election.role)
        if circle is not None
    }
    day = timezone.localdate()
    # The state before the elections, other changes stay
    try:
        with transaction.atomic():
            for election in elections:
                undo_election(election, day)
            before = role_leads_and_members(circles)
            raise _Undone
    except _Undone:
        pass
    announce_changes(circles, before, role_leads_and_members(circles))


def due_elections(circles, *, day=None):
    """``(role, assignment)`` of elected roles whose term ends within 30 days
    or which nobody holds (``assignment`` is None then), except the Circle
    Rep, which may stay unfilled; Role Leads without a term (the role became
    elected while they held it) too"""
    day = day or timezone.localdate()
    limit = day + dt.timedelta(days=REMINDER_DAYS)
    result = []
    for role in elected_roles(circles):
        assignments = list(
            Assignment.objects.current(on=day).filter(role=role).select_related("user")
        )
        if not assignments and role.core_role != REP:
            result.append((role, None))
        result.extend(
            (role, assignment)
            for assignment in assignments
            if not assignment.elected_until or assignment.elected_until <= limit
        )
    return result


class ElectionForm(ModelForm):
    class Meta:
        model = Election
        fields = ["role", "user", "term_ends_on"]
        widgets = {
            "term_ends_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
        }

    def __init__(self, *args, meeting, **kwargs):
        super().__init__(*args, **kwargs)
        self.circle = meeting.circle
        self.fields["role"].queryset = elected_roles([meeting.circle])
        # Only the circle's members may be elected (constitution 5.1.1, 5.1.2);
        # the Circle Rep may stay unfilled
        self.fields["user"].queryset = members(meeting.circle)
        self.fields["user"].required = False
        self.fields["user"].empty_label = _("Nobody (Circle Rep only)")
        self.fields["term_ends_on"].required = False
        self.fields["term_ends_on"].initial = timezone.localdate() + dt.timedelta(
            days=365
        )
        self.fields["term_ends_on"].help_text = _("The day the term ends.")

    def clean_term_ends_on(self):
        term_ends_on = self.cleaned_data["term_ends_on"]
        if term_ends_on and term_ends_on <= timezone.localdate():
            raise forms.ValidationError(_("The term ends in the future."))
        return term_ends_on

    def clean(self):
        data = super().clean()
        role, user = data.get("role"), data.get("user")
        if role and not user and role.core_role != REP:
            self.add_error("user", _("Only the Circle Rep may stay unfilled."))
        elif not user:
            data["term_ends_on"] = None
        elif not data.get("term_ends_on") and "term_ends_on" not in self.errors:
            self.add_error("term_ends_on", _("The day the term ends is required."))
        if (
            role
            and user
            and role.core_role == REP
            and is_circle_lead(user, self.circle)
        ):
            # Constitution 5.1.1
            self.add_error("user", _("A Circle Lead can't be the Circle Rep."))
        return data


@locking_structure
@require_POST
def election_add(request, pk):
    meeting = get_object_or_404(Meeting.objects.select_related("circle"), pk=pk)
    if (
        meeting.kind != Meeting.GOVERNANCE
        or not meeting.is_running
        or not can_run(request.user, meeting)
    ):
        raise PermissionDenied
    form = ElectionForm(request.POST, meeting=meeting)
    if form.is_valid():
        election = record_election(meeting, **form.cleaned_data)
        messages.success(
            request,
            gettext("%(user)s has been elected as %(role)s.")
            % {"user": election.user, "role": election.role}
            if election.user
            else gettext("%(role)s stays unfilled.") % {"role": election.role},
        )
    else:
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
    return redirect(meeting)
