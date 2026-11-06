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
from django.views.decorators.http import require_POST

from governance.accounts.models import User
from governance.forms import ModelForm
from governance.history.update import update_today
from governance.roles.constitution import LEAD, REP
from governance.roles.models import Assignment, Role
from governance.roles.permissions import can_assign, can_end_assignment, members


@contextmanager
def announce(circles):
    """Mails about the assignments changing inside the block (like
    GlassFrog): the people about the roles they get and lose, the circles'
    Secretaries about people joining and leaving. A circle's role in the
    super-circle follows its Circle Leads and Rep, it isn't announced."""
    from governance.notifications import mails

    circles = {circle for circle in circles if circle is not None}

    def holdings():
        return set(
            Assignment.objects
            .current()
            .filter(role__circle__in=circles, role__is_circle=False)
            .values_list("user", "role")
        )

    def memberships():
        # Also people deactivated meanwhile, members() only has active ones
        return {
            circle: set(members(circle).values_list("pk", flat=True))
            | set(
                Assignment.objects
                .current()
                .filter(role__circle=circle)
                .values_list("user", flat=True)
            )
            for circle in circles
        }

    held, joined = holdings(), memberships()
    # Nothing to announce when the block fails
    yield  # noqa: RUF075
    now_held, now_joined = holdings(), memberships()
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
    with announce(circles):
        for assignment in assignments:
            end_assignment(assignment, day)
            after_change(assignment.role, day)


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
            .filter(role=self.instance.role, user=user, focus=data.get("focus", ""))
            .exclude(pk=self.instance.pk)
            .exists()
        ):
            raise forms.ValidationError(
                _("%(user)s already holds this role with this focus.") % {"user": user}
            )
        role = self.instance.role
        if user and role.core_role == LEAD and represents(user, role.circle):
            # Constitution 5.1.1, like electing the Rep
            self.add_error("user", _("A Circle Lead can't be the Circle Rep."))
        return data


def represents(user, circle):
    """Whether the person is the Circle Rep of the circle, or of a sub-circle
    which the circle's Circle Leads lead because nobody else does (1.4.2)"""
    reps = (
        Assignment.objects
        .current()
        .filter(user=user, role__core_role=REP, role__archived_on=None)
        .select_related("role__circle")
    )
    for rep in reps:
        represented = rep.role.circle
        while represented is not None:
            if represented == circle:
                return True
            if Assignment.objects.current().of_core_role(LEAD, represented).exists():
                break  # Led by its own Circle Lead
            represented = represented.circle
    return False


def assignable_role(request, pk, check=can_assign):
    role = get_object_or_404(Role.objects.select_related("circle"), pk=pk)
    if not check(request.user, role):
        raise PermissionDenied
    return role


def assignments(request, pk):
    """The role's holders, with the form to add one (elected roles are
    elected, their holders only removed here)"""
    role = assignable_role(request, pk, check=can_end_assignment)
    form = None
    if can_assign(request.user, role):
        form = AssignmentForm(request.POST or None, role=role)
    elif request.method == "POST":
        raise PermissionDenied
    if form and form.is_valid():
        with transaction.atomic(), announce(affected_circles(role)):
            day = timezone.localdate()
            form.instance.starts_on = day
            assignment = form.save()
            after_change(role, day)
        messages.success(
            request,
            gettext("%(user)s now holds %(role)s.")
            % {"user": assignment.user, "role": role},
        )
        return redirect("role_assignments", pk=role.pk)
    return render(
        request,
        "roles/assignments.html",
        {
            "role": role,
            "ancestors": role.ancestors(),
            "assignments": role.assignments.current().select_related("user"),
            "form": form,
            "can_assign": form is not None,
        },
    )


def assignment_update(request, pk):
    assignment = get_object_or_404(
        Assignment.objects.current().select_related("role__circle", "user"), pk=pk
    )
    role = assignable_role(request, assignment.role_id)
    form = AssignmentForm(request.POST or None, instance=assignment, role=role)
    if form.is_valid():
        form.save()
        return redirect("role_assignments", pk=role.pk)
    return render(
        request,
        "generic/object_form.html",
        {
            "title": gettext("Edit the focus of %(user)s in %(role)s")
            % {"user": assignment.user, "role": role},
            "form": form,
            "cancel_url": reverse("role_assignments", kwargs={"pk": role.pk}),
        },
    )


@require_POST
def assignment_end(request, pk):
    assignment = get_object_or_404(
        Assignment.objects.current().select_related("role__circle", "user"), pk=pk
    )
    role = assignable_role(request, assignment.role_id, check=can_end_assignment)
    with transaction.atomic(), announce(affected_circles(role)):
        day = timezone.localdate()
        end_assignment(assignment, day)
        after_change(role, day)
    messages.success(
        request,
        gettext("%(user)s doesn't hold %(role)s anymore.")
        % {"user": assignment.user, "role": role},
    )
    return redirect("role_assignments", pk=role.pk)
