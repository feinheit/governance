"""Forms filtering lists, like Workbench's: GET forms of selects and
checkboxes which submit when changed (``frontend/filters.js``), a button
without JavaScript, "Reset" when something is chosen
(``generic/_filters.html``)"""

from django import forms
from django.utils.translation import gettext_lazy as _

from governance.roles.models import Role


class FilterForm(forms.Form):
    def __init__(self, data, *args, **kwargs):
        # Only the fields' values, not e.g. the page
        super().__init__(
            {key: value for key, value in data.items() if key in self.base_fields},
            *args,
            **kwargs,
        )
        for name, field in self.fields.items():
            if isinstance(field, RoleField):
                field.add_role(self.data.get(name, ""))
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = "form-check-input"
            elif isinstance(widget, forms.Select):
                widget.attrs["class"] = "form-select form-select-sm"
            else:
                widget.attrs["class"] = "form-control form-control-sm"
        self.is_valid()  # Invalid values filter nothing

    def get(self, name):
        return self.cleaned_data.get(name) if hasattr(self, "cleaned_data") else None

    @property
    def is_filtered(self):
        return any(self.get(name) for name in self.fields)


def circle_choices(label):
    """The circles in the organization's order, indented"""
    return [("", label)] + [
        (str(circle.pk), " " * circle.depth + circle.name)
        for circle in Role.objects.depth_first()
    ]


class CircleField(forms.TypedChoiceField):
    """A circle, its choices read when the form is made"""

    def __init__(self, *, empty_label=None, **kwargs):
        super().__init__(coerce=int, empty_value=None, required=False, **kwargs)
        self.empty_label = empty_label or _("All circles")

    def __deepcopy__(self, memo):
        field = super().__deepcopy__(memo)
        field.choices = circle_choices(field.empty_label)
        return field


class RoleField(CircleField):
    """A circle, or a role (from its page): the circles, and the role
    chosen if it isn't one of them (``FilterForm`` adds it)"""

    def add_role(self, value):
        if not str(value).isdigit() or any(
            key == str(value) for key, _label in self.choices
        ):
            return
        if role := Role.objects.filter(pk=value).first():
            self.choices = [
                *self.choices[:1],
                (str(role.pk), role.name),
                *self.choices[1:],
            ]
