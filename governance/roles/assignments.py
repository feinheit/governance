"""Circle Leads assign people to roles directly, see section 3 of SPEC.md"""

from contextlib import contextmanager

from django import forms
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
from governance.roles.constitution import LEAD, REP
from governance.roles.models import Assignment, Role
from governance.roles.permissions import can_assign, can_end_assignment, members


@contextmanager
def announce(circles):
    """Mails about the assignments changing inside the block (like
    GlassFrog): the people about the roles they get and lose, the circles'
    Secretaries about people joining and leaving. A circle's role in the
    super-circle follows its Circle Leads and Rep, it isn't announced."""
    circles = {circle for circle in circles if circle is not None}
    before = holdings(circles)
    # Nothing to announce when the block fails
    yield  # noqa: RUF075
    announce_changes(circles, before, holdings(circles))


def holdings(circles):
    """``(roles, members)``: who holds which of the circles' roles, and the
    circles' members"""
    roles = set(
        Assignment.objects
        .current()
        .filter(role__circle__in=circles, role__is_circle=False)
        .values_list("user", "role")
    )
    # Also people deactivated meanwhile, members() only has active ones
    joined = {
        circle: set(members(circle).values_list("pk", flat=True))
        | set(
            Assignment.objects
            .current()
            .filter(role__circle=circle)
            .values_list("user", flat=True)
        )
        for circle in circles
    }
    return roles, joined


def announce_changes(circles, before, after):
    """Mails the differences of two ``holdings()``, after committing"""
    from governance.notifications import mails

    (held, joined), (now_held, now_joined) = before, after
    started, ended = now_held - held, held - now_held
    changes = [
        (
            circle,
            now_joined[circle] - joined[circle],
            joined[circle] - now_joined[circle],
        )
        for circle in circles
        if now_joined[circle] != joined[circle]
    ]
    if started or ended:
        transaction.on_commit(lambda: mails.roles_changed(started, ended))
    for circle, new, gone in changes:
        transaction.on_commit(
            lambda circle=circle, new=new, gone=gone: mails.members_changed(
                circle, new, gone
            )
        )


def affected_circles(role):
    """The circles whose roles and members change with the role's holders:
    a Circle Lead also leads the sub-circles nobody leads (1.4.2)"""
    circles = [role.circle]
    if role.core_role in {LEAD, REP} and role.circle:
        circles.append(role.circle.circle)
    if role.core_role == LEAD and role.circle:
        circles.extend(role.circle.sub_circles())
    return circles


def sync_circle_holders(circle, day):
    """The holders of a circle's role are its Circle Leads and Circle Reps

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
            end_assignment(assignment, day)
    for user_id in wanted:
        Assignment.objects.create(role=circle, user_id=user_id, starts_on=day)


def end_assignment(assignment, day):
    """Ends the assignment, removes it if it only started today (a mistake)"""
    if assignment.starts_on == day:
        assignment.delete()
    else:
        assignment.ends_on = day
        assignment.save(update_fields=["ends_on"])


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
            end_assignment(assignment, day)
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
        end_assignment(rep, day)
        after_change(rep.role, day)


class EndingReps(Exception):
    """The change would make Circle Reps lead their circle: confirm first"""

    def __init__(self, reps):
        super().__init__()
        self.reps = reps


def change_assignments(request, role, change):
    """Runs the change of the role's holders with its mails. Circle Reps it
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
        sync_circle_holders(role.circle, day)
    update_today()


class AssignmentForm(ModelForm):
    class Meta:
        model = Assignment
        fields = ["user", "focus"]

    def __init__(self, *args, role, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.role = role
        self.fields["user"].queryset = User.objects.active()
        self.fields["focus"].help_text = _(
            "Optional, e.g. a customer or a topic the person takes care of."
        )
        if self.instance.pk:
            self.fields["user"].disabled = True

    def clean(self):
        data = super().clean()
        user = data.get("user")
        if user and (
            Assignment.objects
            .current()
            .filter(role=self.instance.role, user=user)
            .exclude(pk=self.instance.pk)
            .exists()
        ):
            # Once, the focus lists everything (Assignment's constraint)
            raise forms.ValidationError(
                _("%(user)s already holds this role.") % {"user": user}
            )
        return data


def assignable_role(request, pk, check=can_assign):
    role = get_object_or_404(Role.objects.select_related("circle"), pk=pk)
    if not check(request.user, role):
        raise PermissionDenied
    return role


@locking_structure
def assignments(request, pk):
    """The role's holders, with the form to add one (elected roles are
    elected, their holders only removed here); in a modal only the form"""
    role = assignable_role(request, pk, check=can_end_assignment)
    form = None
    if can_assign(request.user, role):
        form = AssignmentForm(request.POST or None, role=role)
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
        from governance.notifications import mails

        assignment = form.save()
        update_today()  # The history shows changes of the focus
        if assignment.focus != before:
            transaction.on_commit(lambda: mails.focus_changed(assignment, before))
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
            change_assignments(
                request, role, lambda day: end_assignment(assignment, day)
            )
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
    """After a change: ``?next=`` (the role's page), else its holders"""
    return next_url(request) or reverse("role_assignments", kwargs={"pk": role.pk})
