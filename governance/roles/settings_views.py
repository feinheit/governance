"""Settings the Secretary changes, see the decisions in SPEC.md"""

from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext

from governance.forms import ModelForm
from governance.roles.models import Role
from governance.roles.permissions import can_change_settings


class CircleSettingsForm(ModelForm):
    class Meta:
        model = Role
        fields = ["async_acceptance_days"]


class RoleSettingsForm(ModelForm):
    class Meta:
        model = Role
        fields = ["is_elected_by_policy"]


def role_settings(request, pk):
    role = get_object_or_404(Role.objects.select_related("circle"), pk=pk)
    if not can_change_settings(request.user, role):
        raise PermissionDenied
    form_class = CircleSettingsForm if role.is_circle else RoleSettingsForm
    form = form_class(request.POST or None, instance=role)
    if form.is_valid():
        form.save()
        return redirect(role)
    return render(
        request,
        "generic/object_form.html",
        {
            "title": gettext("Settings of %(role)s") % {"role": role},
            "help": gettext(
                "Policies explain the settings, the app uses them. Change both"
                " together."
            ),
            "form": form,
            "cancel_url": role.get_absolute_url(),
        },
    )
