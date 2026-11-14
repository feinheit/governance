"""Editing outside governance: the circle's strategy, metrics, checklist
items, links and notes, the order of accountabilities and domains, see the permissions in the decisions of SPEC.md"""

from functools import partial
from typing import NamedTuple

from django import forms
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext, gettext_lazy as _
from django.views.decorators.http import require_POST

from governance.forms import BLANK_CHOICE_LABEL, ModelForm
from governance.history.update import update_today
from governance.notifications import mails
from governance.roles.models import (
    OPERATIONAL_MODELS,
    ChecklistItem,
    Link,
    Metric,
    Note,
    Role,
    reported_in,
)
from governance.roles.permissions import ALLOWED, NOT_ALLOWED, can_lead


def can_edit_strategy(user, role):
    if not role.is_circle or role.archived_on:
        return NOT_ALLOWED
    return can_lead(user, role)


def can_edit_items(user, role, model, *, whole_circle=False):
    """Metrics: the Circle Lead of the circle reviewing them (its roles', a
    sub-circle's too, the whole circle's). Checklist items, links and notes:
    anybody, Holacracy defines no process for them."""
    if role.archived_on:
        return NOT_ALLOWED
    if model in {ChecklistItem, Link, Note}:
        return ALLOWED
    circle = reported_in(role, whole_circle=whole_circle)
    return can_lead(user, circle) if circle else NOT_ALLOWED


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


MODELS = {model.kind: model for model in OPERATIONAL_MODELS}
FIELDS = {Link: ["title", "url", "description"], Note: ["title", "body"]}


def references(role):
    """The role's links and notes, one list in their order"""
    return sorted(
        [*role.links.all(), *role.notes.all()],
        key=lambda item: (item.position, item._meta.model_name, item.pk),
    )


def next_position(role, model):
    """After the others: links and notes share their positions"""
    if model in {Link, Note}:
        items = references(role)
    else:
        items = model.objects.filter(role=role)
    return max((item.position + 1 for item in items), default=0)


def order_key(item):
    """Links and notes are ``link-3`` and ``note-5``, texts their IDs"""
    if isinstance(item, (Link, Note)):
        return f"{item._meta.model_name}-{item.pk}"
    return str(item.pk)


class Reporter(NamedTuple):
    """A choice of who reports a checklist item or metric"""

    role: Role
    whole_circle: bool
    label: str
    # In the group of the circle's roles
    grouped: bool = False

    @property
    def key(self):
        """The choice's value: two choices may have the same role, the circle"""
        return f"{self.role.pk}-whole" if self.whole_circle else str(self.role.pk)


def circle_reporters(circle):
    """A circle's page: the whole circle, the circle in its super-circle and
    the circle's roles (a sub-circle too) in its own"""
    reporters = [
        Reporter(
            role=circle,
            whole_circle=True,
            label=gettext("%(circle)s (whole circle)") % {"circle": circle},
        )
    ]
    if circle.circle and not circle.circle.archived_on:
        reporters.append(
            Reporter(
                role=circle,
                whole_circle=False,
                label=gettext("%(circle)s in %(super_circle)s")
                % {"circle": circle, "super_circle": circle.circle},
            )
        )
    reporters.extend(
        Reporter(role=role, whole_circle=False, label=role.name, grouped=True)
        for role in circle.roles.active().order_by("position", "name")
    )
    return reporters


def role_reporters(role):
    """A role's page: the role in its circle"""
    if not role.circle:
        return []
    return [
        Reporter(
            role=role,
            whole_circle=False,
            label=gettext("%(role)s in %(circle)s")
            % {"role": role, "circle": role.circle},
        )
    ]


def page_reporters(request, item):
    """The choices of the page the form was opened on: a circle's page
    passes ``?circle=``, adding on a circle's page adds to the circle"""
    pk = request.GET.get("circle", "")
    page = pk.isdigit() and Role.objects.active().circles().filter(pk=pk).first()
    if page:
        return circle_reporters(page)
    if item.role.is_circle:
        return circle_reporters(item.role)
    return role_reporters(item.role)


def item_reporters(request, item, model):
    """The choices of who reports a checklist item or metric: the page's,
    those the user may edit it for, and the item's current one in any case
    (e.g. a role's item of the whole circle, from when it was a circle)"""
    if model not in {Metric, ChecklistItem}:
        return None
    choices = {reporter.key: reporter for reporter in page_reporters(request, item)}
    current = Reporter(
        role=item.role,
        whole_circle=item.whole_circle,
        label=gettext("%(circle)s (whole circle)") % {"circle": item.role}
        if item.whole_circle
        else str(item.role),
    )
    choices.setdefault(current.key, current)
    return {
        key: reporter
        for key, reporter in choices.items()
        if key == current.key
        or can_edit_items(
            request.user, reporter.role, model, whole_circle=reporter.whole_circle
        )
    }


class ItemForm(ModelForm):
    class Meta:
        fields = ["description", "frequency", "link"]
        widgets = {"description": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, reporters=None, **kwargs):
        """``reporters``: ``{key: Reporter}`` (``item_reporters()``)"""
        super().__init__(*args, **kwargs)
        self.reporters = reporters
        if not reporters:
            return
        adding = self.instance._state.adding
        if not adding:
            initial = Reporter(
                role=self.instance.role,
                whole_circle=self.instance.whole_circle,
                label="",
            ).key
        elif len(reporters) == 1:  # A role's page
            initial = next(iter(reporters))
        else:  # Chosen explicitly
            initial = None
        ungrouped = [(k, r.label) for k, r in reporters.items() if not r.grouped]
        grouped = [(k, r.label) for k, r in reporters.items() if r.grouped]
        self.fields["reported_by"] = forms.ChoiceField(
            label=_("Reported by"),
            choices=[
                ("", BLANK_CHOICE_LABEL),
                *ungrouped,
                *([(_("Roles"), grouped)] if grouped else []),
            ],
            # Without it, existing ones stay unchanged, so do new ones with
            # only one choice
            required=adding and len(reporters) > 1,
            initial=initial,
        )
        self.order_fields(["description", "reported_by"])

    def save(self, *args, **kwargs):
        if self.reporters and (key := self.cleaned_data.get("reported_by")):
            reporter = self.reporters[key]
            self.instance.role = reporter.role
            self.instance.whole_circle = reporter.whole_circle
        return super().save(*args, **kwargs)


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
        item = model(role=role, position=next_position(role, model))
        if model in {Metric, ChecklistItem}:
            # Added on a circle's page: checks the permission for the whole
            # circle's, "Reported by" chooses
            item.whole_circle = role.is_circle
    whole_circle = getattr(item, "whole_circle", False)
    if not (
        right := can_edit_items(request.user, role, model, whole_circle=whole_circle)
    ):
        raise PermissionDenied
    form = item_form(model)(
        request.POST or None,
        instance=item,
        reporters=item_reporters(request, item, model),
    )
    if form.is_valid():
        form.save()
        update_today()  # The history shows them on request
        # Back to the page it was edited on
        page = request.GET.get("circle", "")
        return redirect(page.isdigit() and Role.objects.filter(pk=page).first() or role)
    return render(
        request,
        "generic/object_form.html",
        {
            "title": {
                Metric: gettext("Metric of %(role)s"),
                ChecklistItem: gettext("Checklist item of %(role)s"),
                Link: gettext("Link of %(role)s"),
                Note: gettext("Note of %(role)s"),
            }[model]
            % {"role": role},
            "form": form,
            "right": right,
            "cancel_url": role.get_absolute_url(),
        },
    )


def item_delete(request, kind, pk):
    """Deleting a metric, checklist item, link or note, confirmed first (in a
    modal on the role's page)"""
    model = MODELS.get(kind)
    if model is None:
        raise PermissionDenied
    item = get_object_or_404(model.objects.select_related("role"), pk=pk)
    if not (
        right := can_edit_items(
            request.user,
            item.role,
            model,
            whole_circle=getattr(item, "whole_circle", False),
        )
    ):
        raise PermissionDenied
    if request.method == "POST":
        item.delete()
        update_today()
        return redirect(item.role)
    return render(
        request,
        "generic/confirm.html",
        {
            "question": {
                Metric: gettext("Delete this metric?"),
                ChecklistItem: gettext("Delete this checklist item?"),
                Link: gettext("Delete this link?"),
                Note: gettext("Delete this note?"),
            }[model],
            "help": item.role,
            "text": item,
            "submit_label": gettext("Delete"),
            "right": right,
            "cancel_url": item.role.get_absolute_url(),
        },
    )


# Their order isn't governance: anybody changes it, the history doesn't
# count it as a change (decided 2026-11-09); links and notes are one list
ORDERED_TEXTS = {"accountabilities", "domains", "references"}


def reorderable_texts(pk, kind):
    """The role and its accountabilities, domains or references (links and
    notes)"""
    if kind not in ORDERED_TEXTS:
        raise Http404
    role = get_object_or_404(Role.objects.active(), pk=pk)
    if kind == "references":
        return role, references(role)
    return role, list(getattr(role, kind).all())


def save_order(texts):
    for position, text in enumerate(texts):
        if text.position != position:
            text.position = position
            text.save(update_fields=["position"])


@require_POST
@transaction.atomic
def texts_order(request, pk, kind):
    """The accountabilities, domains or references dragged into an order
    (frontend/sortable.js): their keys (``order_key()``) in the new order,
    missing ones keep theirs after them"""
    role, texts = reorderable_texts(pk, kind)
    by_key = {order_key(text): text for text in texts}
    keys = [key for key in request.POST.getlist("ids") if key in by_key]
    order = [*dict.fromkeys(keys), *(key for key in by_key if key not in keys)]
    save_order([by_key[key] for key in order])
    return redirect(role)


@require_POST
@transaction.atomic
def text_move(request, pk, kind, key):
    """Moves an accountability, domain or reference up or down, without
    JavaScript"""
    role, texts = reorderable_texts(pk, kind)
    index = next((i for i, text in enumerate(texts) if order_key(text) == key), None)
    if index is None:
        raise Http404
    other = index + (-1 if request.POST.get("direction") == "up" else 1)
    if 0 <= other < len(texts):
        texts[index], texts[other] = texts[other], texts[index]
        save_order(texts)
    return redirect(role)
