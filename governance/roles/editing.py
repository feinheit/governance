"""Editing outside governance: the circle's strategy, metrics, checklist
items and links, the order of accountabilities and domains, see the permissions in the decisions of SPEC.md"""

from functools import partial

from django import forms
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext
from django.views.decorators.http import require_POST

from governance.forms import ModelForm
from governance.history.update import update_today
from governance.notifications import mails
from governance.roles.models import ChecklistItem, Link, Metric, Role
from governance.roles.permissions import ALLOWED, NOT_ALLOWED, can_lead


def can_edit_strategy(user, role):
    if not role.is_circle or role.archived_on:
        return NOT_ALLOWED
    return can_lead(user, role)


def can_edit_items(user, role, model):
    """Metrics: the Circle Lead (a circle's own, or its roles'). Checklist
    items and links: anybody, Holacracy defines no process for them."""
    if role.archived_on:
        return NOT_ALLOWED
    if model in {ChecklistItem, Link}:
        return ALLOWED
    return can_lead(user, role.governing_circle)


class StrategyForm(ModelForm):
    class Meta:
        model = Role
        fields = ["strategy"]
        widgets = {"strategy": forms.Textarea(attrs={"rows": 12})}


def strategy(request, pk):
    role = get_object_or_404(Role, pk=pk)
    if not (right := can_edit_strategy(request.user, role)):
        raise PermissionDenied
    before = role.strategy
    form = StrategyForm(request.POST or None, instance=role)
    if form.is_valid():
        role = form.save()
        update_today()
        if role.strategy != before:
            transaction.on_commit(
                partial(
                    mails.strategy_changed, role, before, role.strategy, request.user
                )
            )
        return redirect(role)
    return render(
        request,
        "generic/object_form.html",
        {
            "title": gettext("Strategy of %(circle)s") % {"circle": role},
            "help": gettext(
                "The Circle Leads set the strategy outside governance. The"
                " members of the circle and its sub-circles get a mail."
            ),
            "form": form,
            "right": right,
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
    if not (right := can_edit_items(request.user, role, model)):
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
            "right": right,
            "cancel_url": role.get_absolute_url(),
        },
    )


def item_delete(request, kind, pk):
    """Deleting a metric, checklist item or link, confirmed first (in a
    modal on the role's page)"""
    model = MODELS.get(kind)
    if model is None:
        raise PermissionDenied
    item = get_object_or_404(model.objects.select_related("role"), pk=pk)
    if not (right := can_edit_items(request.user, item.role, model)):
        raise PermissionDenied
    if request.method == "POST":
        item.delete()
        return redirect(item.role)
    return render(
        request,
        "generic/confirm.html",
        {
            "question": {
                Metric: gettext("Delete this metric?"),
                ChecklistItem: gettext("Delete this checklist item?"),
                Link: gettext("Delete this link?"),
            }[model],
            "help": item.role,
            "text": item,
            "submit_label": gettext("Delete"),
            "right": right,
            "cancel_url": item.role.get_absolute_url(),
        },
    )


# Their order isn't governance: anybody changes it, the history doesn't
# count it as a change (decided 2026-11-09)
ORDERED_TEXTS = {"accountabilities", "domains"}


def reorderable_texts(pk, kind):
    """The role and its accountabilities or domains"""
    if kind not in ORDERED_TEXTS:
        raise Http404
    role = get_object_or_404(Role.objects.active(), pk=pk)
    return role, list(getattr(role, kind).all())


def save_order(texts):
    for position, text in enumerate(texts):
        if text.position != position:
            text.position = position
            text.save(update_fields=["position"])


@require_POST
@transaction.atomic
def texts_order(request, pk, kind):
    """The accountabilities or domains dragged into an order
    (frontend/sortable.js): their IDs in the new order, missing ones keep
    theirs after them"""
    role, texts = reorderable_texts(pk, kind)
    by_pk = {text.pk: text for text in texts}
    ids = [
        int(value)
        for value in request.POST.getlist("ids")
        if value.isdigit() and int(value) in by_pk
    ]
    order = [*dict.fromkeys(ids), *(pk for pk in by_pk if pk not in ids)]
    save_order([by_pk[pk] for pk in order])
    return redirect(role)


@require_POST
@transaction.atomic
def text_move(request, pk, kind, text_pk):
    """Moves an accountability or domain up or down, without JavaScript"""
    role, texts = reorderable_texts(pk, kind)
    index = next((i for i, text in enumerate(texts) if text.pk == text_pk), None)
    if index is None:
        raise Http404
    other = index + (-1 if request.POST.get("direction") == "up" else 1)
    if 0 <= other < len(texts):
        texts[index], texts[other] = texts[other], texts[index]
        save_order(texts)
    return redirect(role)
