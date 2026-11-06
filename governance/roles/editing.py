"""Editing outside governance: the circle's strategy, metrics, checklist
items and links, see the permissions in the decisions of SPEC.md"""

from django import forms
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext
from django.views.decorators.http import require_POST

from governance.forms import ModelForm
from governance.roles.models import ChecklistItem, Link, Metric, Role
from governance.roles.permissions import can_lead


def can_edit_strategy(user, role):
    return role.is_circle and not role.archived_on and can_lead(user, role)


def can_edit_items(user, role, model):
    """Metrics: the Circle Lead (a circle's own, or its roles'). Checklist
    items and links: anybody, Holacracy defines no process for them."""
    if role.archived_on:
        return False
    if model in {ChecklistItem, Link}:
        return True
    return can_lead(user, role if role.is_circle else role.circle)


class StrategyForm(ModelForm):
    class Meta:
        model = Role
        fields = ["strategy"]
        widgets = {"strategy": forms.Textarea(attrs={"rows": 12})}


def strategy(request, pk):
    role = get_object_or_404(Role, pk=pk)
    if not can_edit_strategy(request.user, role):
        raise PermissionDenied
    form = StrategyForm(request.POST or None, instance=role)
    if form.is_valid():
        form.save()
        return redirect(role)
    return render(
        request,
        "generic/object_form.html",
        {
            "title": gettext("Strategy of %(circle)s") % {"circle": role},
            "help": gettext("The Circle Leads set the strategy outside governance."),
            "form": form,
            "cancel_url": role.get_absolute_url(),
        },
    )


MODELS = {"metrics": Metric, "checklist": ChecklistItem, "links": Link}
FIELDS = {Link: ["title", "url", "description"]}


class ItemForm(ModelForm):
    class Meta:
        fields = ["description", "frequency", "link"]
        widgets = {"description": forms.Textarea(attrs={"rows": 2})}


def item_form(model):
    meta = {"model": model}
    if model in FIELDS:
        meta |= {"fields": FIELDS[model], "widgets": {}}
    return type("Form", (ItemForm,), {"Meta": type("Meta", (ItemForm.Meta,), meta)})


def item_edit(request, kind, pk=None, role_pk=None):
    model = MODELS.get(kind)
    if model is None:
        raise PermissionDenied
    if pk:
        item = get_object_or_404(model.objects.select_related("role"), pk=pk)
        role = item.role
    else:
        role = get_object_or_404(Role, pk=role_pk)
        item = model(
            role=role,
            position=model.objects.filter(role=role).count(),
        )
    if not can_edit_items(request.user, role, model):
        raise PermissionDenied
    form = item_form(model)(request.POST or None, instance=item)
    if form.is_valid():
        form.save()
        return redirect(role)
    return render(
        request,
        "generic/object_form.html",
        {
            "title": {
                Metric: gettext("Metric of %(role)s"),
                ChecklistItem: gettext("Checklist item of %(role)s"),
                Link: gettext("Link of %(role)s"),
            }[model]
            % {"role": role},
            "form": form,
            "cancel_url": role.get_absolute_url(),
        },
    )


@require_POST
def item_delete(request, kind, pk):
    model = MODELS.get(kind)
    if model is None:
        raise PermissionDenied
    item = get_object_or_404(model.objects.select_related("role"), pk=pk)
    if not can_edit_items(request.user, item.role, model):
        raise PermissionDenied
    item.delete()
    return redirect(item.role)
