"""Circle Leads assign people to roles directly, see section 3 of SPEC.md"""

from functools import partial

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext, gettext_lazy as _

from governance.accounts.models import User
from governance.forms import ModelForm, next_url
from governance.history.update import update_today
from governance.locking import locking_structure
from governance.notifications import mails
from governance.notifications.role_leads import announce
from governance.roles.constitution import LEAD, REP
from governance.roles.models import Assignment, Role
from governance.roles.permissions import can_assign, can_end_assignment


def affected_circles(role):
    """The circles whose roles and members change with the role's Role Leads:
    a Circle Lead also leads the sub-circles nobody leads (1.4.2)"""
    circles = [role.circle]
    if role.core_role in {LEAD, REP} and role.circle:
        circles.append(role.circle.circle)
    if role.core_role == LEAD and role.circle:
        circles.extend(role.circle.sub_circles())
    return circles


def sync_circle_role_leads(circle, day):
    """The Role Leads of a circle's role are its Circle Leads and Circle Reps

    GlassFrog stores them like this and the circle page shows them in the
    super-circle, so the circle's role follows its core roles.
    """
    current = Assignment.objects.current(on=day)
    wanted = set(
        current.of_core_role([LEAD, REP], circle).values_list("user", flat=True)
    )
    for assignment in current.filter(role=circle):
        if assignment.user_id in wanted:
            wanted.discard(assignment.user_id)
        else:
            assignment.end(day)
    for user_id in wanted:
        Assignment.objects.create(role=circle, user_id=user_id, starts_on=day)


def end_assignments_of(user, day):
    """Somebody leaves (deactivated): their roles end, like removing them
    one by one, a Circle Lead's role in the super-circle too"""
    assignments = list(
        Assignment.objects.current().filter(user=user).select_related("role__circle")
    )
    circles = [c for a in assignments for c in affected_circles(a.role)]
    before = reps_leading_their_circle()
    with announce(circles):
        for assignment in assignments:
            assignment.end(day)
            after_change(assignment.role, day)
        # Nobody to warn here
        end_reps(new_reps_leading(before), day)


def reps_leading_their_circle():
    """The assignments of Circle Reps who also lead their circle, e.g. from
    the super-circle (1.4.2), which the constitution forbids (5.1.1)"""
    from governance.roles.permissions import is_circle_lead

    return [
        rep
        for rep in Assignment.objects
        .current()
        .filter(role__core_role=REP, role__archived_on=None)
        .select_related("user", "role__circle")
        if is_circle_lead(rep.user, rep.role.circle)
    ]


def new_reps_leading(before):
    return [rep for rep in reps_leading_their_circle() if rep not in before]


def end_reps(reps, day):
    """The Circle Reps leading their circle now resign, the circle elects
    another one"""
    for rep in reps:
        rep.end(day)
        after_change(rep.role, day)


class EndingReps(Exception):
    """The change would make Circle Reps lead their circle: confirm first"""

    def __init__(self, reps):
        super().__init__()
        self.reps = reps


def change_assignments(request, role, change):
    """Runs the change of the role's Role Leads with its mails. Circle Reps it
    makes lead their circle (5.1.1) end with it once ``end_reps`` confirms
    it; until then ``EndingReps`` rolls the change back."""
    before = reps_leading_their_circle()
    with transaction.atomic(), announce(affected_circles(role)):
        day = timezone.localdate()
        result = change(day)
        after_change(role, day)
        if reps := new_reps_leading(before):
            if not request.POST.get("end_reps"):
                raise EndingReps(reps)
            end_reps(reps, day)
    return result


def after_change(role, day):
    if role.core_role in {LEAD, REP}:
        sync_circle_role_leads(role.circle, day)
    update_today()


class AssignmentForm(ModelForm):
    class Meta:
        model = Assignment
        fields = ["user", "focus"]

    def __init__(self, *args, role, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.role = role
        if not self.instance._state.adding:
            # Only the focus changes, the title names the person
            del self.fields["user"]
        else:
            # Once per person, the focus lists everything (Assignment's
            # constraint): those holding the role already aren't offered
            self.fields["user"].queryset = User.objects.active().exclude(
                assignments__in=role.assignments.current()
            )
        self.fields["focus"].help_text = _(
            "Optional, e.g. a customer or a topic the person takes care of."
        )


def assignable_role(request, pk, check=can_assign):
    role = get_object_or_404(Role.objects.select_related("circle"), pk=pk)
    if not check(request.user, role):
        raise PermissionDenied
    return role


@locking_structure
def assignments(request, pk):
    """The role's Role Leads, with the form to add one (elected roles are
    elected, their Role Leads only removed here); in a modal only the form"""
    role = assignable_role(request, pk, check=can_end_assignment)
    form = None
    if can_assign(request.user, role):
        # ?user= preselects the person (the circle's members)
        form = AssignmentForm(
            request.POST or None, role=role, initial={"user": request.GET.get("user")}
        )
    elif request.method == "POST":
        raise PermissionDenied
    reps = None
    if form and form.is_valid():

        def assign(day):
            form.instance.starts_on = day
            return form.save()

        try:
            assignment = change_assignments(request, role, assign)
        except EndingReps as exc:
            reps = exc.reps
        else:
            messages.success(
                request,
                gettext("%(user)s now holds %(role)s.")
                % {"user": assignment.user, "role": role},
            )
            return redirect(back(request, role))
    return render_assignments(request, role, form, reps=reps)


def render_assignments(request, role, form, *, reps=None):
    """``reps``: the Circle Reps the change ends"""
    return render(
        request,
        "roles/assignments.html",
        {
            "role": role,
            "ancestors": role.ancestors(),
            "assignments": role.assignments.current().select_related("user"),
            "form": form,
            "can_assign": form is not None,
            "reps": reps,
            "right": can_end_assignment(request.user, role),
        },
    )


@locking_structure
def assignment_update(request, pk):
    assignment = get_object_or_404(
        Assignment.objects.current().select_related("role__circle", "user"), pk=pk
    )
    role = assignable_role(request, assignment.role_id)
    before = assignment.focus
    form = AssignmentForm(request.POST or None, instance=assignment, role=role)
    if form.is_valid():
        assignment = form.save()
        update_today()  # The history shows changes of the focus
        if assignment.focus != before:
            transaction.on_commit(partial(mails.focus_changed, assignment, before))
        return redirect(back(request, role))
    return render(
        request,
        "generic/object_form.html",
        {
            "title": gettext("Edit the focus of %(user)s in %(role)s")
            % {"user": assignment.user, "role": role},
            "form": form,
            "right": can_assign(request.user, role),
            "cancel_url": back(request, role),
        },
    )


@locking_structure
def assignment_end(request, pk):
    """Removing somebody from a role, confirmed first (in a modal on the
    role's page), also when it ends Circle Rep assignments (5.1.1)"""
    assignment = get_object_or_404(
        Assignment.objects.current().select_related("role__circle", "user"), pk=pk
    )
    role = assignable_role(request, assignment.role_id, check=can_end_assignment)
    reps = None
    if request.method == "POST":
        try:
            change_assignments(request, role, assignment.end)
        except EndingReps as exc:
            reps = exc.reps
        else:
            messages.success(
                request,
                gettext("%(user)s doesn't hold %(role)s anymore.")
                % {"user": assignment.user, "role": role},
            )
            return redirect(back(request, role))
    return render(
        request,
        "roles/assignment_end.html",
        {
            "assignment": assignment,
            "role": role,
            "reps": reps,
            "right": can_end_assignment(request.user, role),
        },
    )


def back(request, role):
    """After a change: ``?next=`` (the role's page), else its Role Leads"""
    return next_url(request) or reverse("role_assignments", kwargs={"pk": role.pk})
