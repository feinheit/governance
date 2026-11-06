"""Circle Leads assign people to roles directly, see section 3 of SPEC.md"""

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
from governance.roles.permissions import can_assign


def sync_circle_holders(circle, day):
    """The holders of a circle's role are its Circle Leads and Circle Reps

    GlassFrog stores them like this and the circle page shows them in the
    super-circle, so the circle's role follows its core roles.
    """
    current = Assignment.objects.current(on=day)
    wanted = set(
        current
        .filter(role__circle=circle, role__core_role__in=[LEAD, REP])
        .filter(role__archived_on=None)
        .values_list("user", flat=True)
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
    for assignment in Assignment.objects.current().filter(user=user):
        end_assignment(assignment, day)
        after_change(assignment.role, day)


def after_change(role, day):
    if role.core_role == LEAD:
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
        if (
            user
            and role.core_role == LEAD
            and Assignment.objects
            .current()
            .filter(user=user, role__circle=role.circle_id, role__core_role=REP)
            .exists()
        ):
            # Constitution 5.1.1, like electing the Rep
            self.add_error("user", _("A Circle Lead can't be the Circle Rep."))
        return data


def assignable_role(request, pk):
    role = get_object_or_404(Role.objects.select_related("circle"), pk=pk)
    if not can_assign(request.user, role):
        raise PermissionDenied
    return role


def assignments(request, pk):
    """The role's holders, with the form to add one"""
    role = assignable_role(request, pk)
    form = AssignmentForm(request.POST or None, role=role)
    if form.is_valid():
        with transaction.atomic():
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
    role = assignable_role(request, assignment.role_id)
    with transaction.atomic():
        day = timezone.localdate()
        end_assignment(assignment, day)
        after_change(role, day)
    messages.success(
        request,
        gettext("%(user)s doesn't hold %(role)s anymore.")
        % {"user": assignment.user, "role": role},
    )
    return redirect("role_assignments", pk=role.pk)
