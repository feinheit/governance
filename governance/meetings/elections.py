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
from governance.meetings.access import can_run
from governance.meetings.models import Election, Meeting
from governance.roles.assignments import (
    affected_circles,
    announce,
    end_assignment,
    sync_circle_holders,
)
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
    """The elected person holds the role until the term ends"""
    with announce(affected_circles(role)):
        return _record_election(meeting, role, user, term_ends_on)


def _record_election(meeting, role, user, term_ends_on):
    day = timezone.localdate()
    reelected = False
    for assignment in Assignment.objects.current().filter(role=role):
        if assignment.user_id == user.pk:
            assignment.elected_until = term_ends_on
            assignment.save(update_fields=["elected_until"])
            reelected = True
        else:
            end_assignment(assignment, day)
    if not reelected:
        Assignment.objects.create(
            role=role, user=user, starts_on=day, elected_until=term_ends_on
        )
    if role.core_role == REP:
        sync_circle_holders(role.circle, day)
    update_today()
    return Election.objects.create(
        meeting=meeting, role=role, user=user, term_ends_on=term_ends_on
    )


def due_elections(circles, *, day=None):
    """``(role, assignment)`` of elected roles whose term ends within 30 days
    or which nobody holds (``assignment`` is None then)"""
    day = day or timezone.localdate()
    limit = day + dt.timedelta(days=REMINDER_DAYS)
    result = []
    for role in elected_roles(circles):
        assignments = list(
            Assignment.objects.current(on=day).filter(role=role).select_related("user")
        )
        if not assignments:
            result.append((role, None))
        result.extend(
            (role, assignment)
            for assignment in assignments
            if assignment.elected_until and assignment.elected_until <= limit
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
        # Only the circle's members may be elected (constitution 5.1.1, 5.1.2)
        self.fields["user"].queryset = members(meeting.circle)
        self.fields["term_ends_on"].initial = timezone.localdate() + dt.timedelta(
            days=365
        )
        self.fields["term_ends_on"].help_text = _("The day the term ends.")

    def clean(self):
        data = super().clean()
        role, user = data.get("role"), data.get("user")
        if (
            role
            and user
            and role.core_role == REP
            and is_circle_lead(user, self.circle)
        ):
            # Constitution 5.1.1
            self.add_error("user", _("A Circle Lead can't be the Circle Rep."))
        return data


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
            % {"user": election.user, "role": election.role},
        )
    else:
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
    return redirect(meeting)
