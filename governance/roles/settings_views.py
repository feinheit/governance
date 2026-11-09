"""Settings the Secretary changes, see the decisions in SPEC.md"""

from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.html import escape
from django.utils.translation import gettext, ngettext

from governance.forms import ModelForm
from governance.roles.models import Role
from governance.roles.permissions import can_change_settings


class CircleSettingsForm(ModelForm):
    class Meta:
        model = Role
        fields = ["async_acceptance_days"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # A decision, see section 10 of SPEC.md: the constitution applies a
        # policy changing a default process only in its circle unless it
        # says otherwise (5.2.1)
        field = self.fields["async_acceptance_days"]
        field.help_text = gettext(
            "In calendar days. Sub-circles without a deadline of their own use"
            " this one, so the policy setting it should say that it applies to"
            " all sub-circles (constitution 5.2.1)."
        )
        # What applies when empty: the nearest super-circle's, else none
        circle = self.instance.circle
        while circle is not None and circle.async_acceptance_days is None:
            circle = circle.circle
        if circle is None:
            empty = gettext(
                "Empty: no time limit, async proposals are only adopted once"
                " everybody consented."
            )
        else:
            days = circle.async_acceptance_days
            field.widget.attrs["placeholder"] = days
            # Help texts are rendered unescaped
            empty = ngettext(
                "Empty: %(days)s day, set by %(circle)s.",
                "Empty: %(days)s days, set by %(circle)s.",
                days,
            ) % {"days": days, "circle": escape(circle)}
        field.help_text = f"{empty} {field.help_text}"


class RoleSettingsForm(ModelForm):
    class Meta:
        model = Role
        fields = ["is_elected_by_policy"]


def role_settings(request, pk):
    role = get_object_or_404(Role.objects.select_related("circle"), pk=pk)
    if not (right := can_change_settings(request.user, role)):
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
            "right": right,
            "cancel_url": role.get_absolute_url(),
        },
    )
