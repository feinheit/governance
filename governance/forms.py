from django import forms
from django.forms.renderers import TemplatesSetting
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _


# Django 6.1's label of empty choices (``BLANK_CHOICE_LABEL``) has no German
# translation yet: ours, kept in the catalog because it appears here
BLANK_CHOICE_LABEL = _("- Select an option -")


def next_url(request):
    """Where to go after saving, e.g. back to the meeting amending the
    proposal or to the circle's page (``?next=`` or a ``next`` field)"""
    url = request.POST.get("next") or request.GET.get("next")
    if url and url_has_allowed_host_and_scheme(
        url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return url
    return None


class Renderer(TemplatesSetting):
    """Fields with Bootstrap's markup, see ``forms/field.html``"""

    field_template_name = "forms/field.html"


class BootstrapMixin:
    """Bootstrap's classes on the widgets, also of fields added later"""

    def __getitem__(self, name):
        widget = self.fields[name].widget
        if isinstance(
            widget,
            forms.CheckboxInput | forms.RadioSelect | forms.CheckboxSelectMultiple,
        ):
            css = "form-check-input"
        elif isinstance(widget, forms.Select | forms.SelectMultiple):
            css = "form-select"
        else:
            css = "form-control"
        classes = widget.attrs.get("class", "").split()
        if css not in classes:
            widget.attrs["class"] = " ".join([*classes, css])
        if isinstance(widget, forms.Textarea):
            # Autocompleting @mentions of roles, see mentions.js
            widget.attrs.setdefault("data-mentions", "")
        return super().__getitem__(name)


class Form(BootstrapMixin, forms.Form):
    pass


class ModelForm(BootstrapMixin, forms.ModelForm):
    pass
