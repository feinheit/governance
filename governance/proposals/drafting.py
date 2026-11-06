"""Drafting proposals: forms per operation building the instructions

The proposal page never shows instructions; these forms build them (add,
change and remove roles and policies, turn a role into a circle and back)
and the page renders them as a diff, see ``describe()``. Editing a role or
policy again replaces the instructions built for it before.
"""

import json
import re

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext, gettext_lazy as _
from django.views.decorators.http import require_POST

from governance.forms import Form, ModelForm, next_url
from governance.proposals.instructions import MARKERS, NEW_KEY, new_key, subject_of
from governance.proposals.models import Proposal
from governance.roles.constitution import CORE_ROLES, LEAD
from governance.roles.models import Policy, Role
from governance.roles.permissions import proposer_roles


TEXT_KINDS = [
    ("accountabilities", _("Accountability"), _("New accountabilities")),
    ("domains", _("Domain"), _("New domains")),
]


# Instructions ################################################################


def done(request, proposal):
    """Back to the proposal, or to ``next``: in a meeting (htmx) its region
    is reloaded in place"""
    if url := next_url(request):
        if request.headers.get("HX-Request"):
            return HttpResponse(
                headers={
                    "HX-Location": json.dumps({
                        "path": url,
                        "target": "#meeting",
                        "select": "#meeting",
                        "swap": "outerHTML show:none",
                    })
                }
            )
        return redirect(url)
    return redirect(proposal)


def cancel_url(request, proposal):
    return next_url(request) or proposal.get_absolute_url()


def instructions_of(proposal, key):
    return [i for i in proposal.instructions if subject_of(i["path"]) == key]


def is_managed(instruction, key):
    """Instructions the role or policy form builds (not removing, converting)"""
    path = instruction["path"]
    return not (
        (instruction["op"] == "remove" and path == f"/{key}")
        or instruction["op"] == "move"
        or path.endswith("/supporting_circle")
    )


def replace_subject(proposal, key, new, *, managed_only=True):
    """Replaces the instructions of a subject, keeps the others' order"""
    kept, position = [], None
    for instruction in proposal.instructions:
        if subject_of(instruction["path"]) != key or (
            managed_only and not is_managed(instruction, key)
        ):
            kept.append(instruction)
        elif position is None:
            position = len(kept)
    if position is None:
        position = len(kept)
    proposal.instructions = normalize(kept[:position] + new + kept[position:])


def normalize(instructions):
    """One ``test`` per existing subject, first, and only if it changes"""
    changed = {subject_of(i["path"]) for i in instructions if i["op"] != "test"}
    result, tested = [], set()
    for instruction in instructions:
        if instruction["op"] == "test":
            key = subject_of(instruction["path"])
            if key not in changed or key in tested:
                continue
            tested.add(key)
        result.append(instruction)
    return result


def lines(text):
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def role_instructions(proposal, key, role, data):
    """Instructions turning the role (or a new one) into the form's data"""
    taken = list(proposal.instructions)
    result = []

    def add(instruction):
        result.append(instruction)
        taken.append(instruction)

    base = f"/roles/{key}"
    if role is None:
        add({"op": "add", "path": base})
        add({"op": "add", "path": f"{base}/name", "value": data["name"]})
        if data["purpose"]:
            add({"op": "add", "path": f"{base}/aim", "value": data["purpose"]})
    else:
        add({"op": "test", "path": base})
        if not role.core_role:
            for field, path in [("name", "name"), ("purpose", "aim")]:
                if data[field] != getattr(role, field):
                    add({
                        "op": "replace",
                        "path": f"{base}/{path}",
                        "original_value": getattr(role, field),
                        "value": data[field],
                    })
        for kind, _label, _new_label in TEXT_KINDS:
            for obj in getattr(role, kind).all():
                text = data[f"{kind}-{obj.pk}"]
                if not text:
                    add({
                        "op": "remove",
                        "path": f"{base}/{kind}/{obj.pk}",
                        "original_value": obj.text,
                    })
                elif text != obj.text:
                    add({
                        "op": "replace",
                        "path": f"{base}/{kind}/{obj.pk}/description",
                        "original_value": obj.text,
                        "value": text,
                    })
    for kind, _label, _new_label in TEXT_KINDS:
        for text in lines(data[f"new_{kind}"]):
            add({
                "op": "add",
                "path": f"{base}/{kind}/{new_key(taken)}/description",
                "value": text,
            })
    return result


def policy_instructions(key, policy, data):
    base = f"/policies/{key}"
    if policy is None:
        return [
            {"op": "add", "path": base},
            {"op": "add", "path": f"{base}/title", "value": data["title"]},
            {"op": "add", "path": f"{base}/body", "value": data["body"]},
        ]
    return [{"op": "test", "path": base}] + [
        {
            "op": "replace",
            "path": f"{base}/{field}",
            "original_value": getattr(policy, field),
            "value": data[field],
        }
        for field in ["title", "body"]
        if data[field] != getattr(policy, field)
    ]


def proposed_values(proposal, key, obj, fields):
    """The values of the subject's fields with the proposal's changes"""
    values = {field: getattr(obj, attribute, "") for field, attribute in fields}
    paths = {f"/{key}/{field}": field for field, _attribute in fields}
    for instruction in instructions_of(proposal, key):
        if (field := paths.get(instruction["path"])) and instruction["op"] != "remove":
            values[field] = instruction.get("value") or ""
    return values


# Forms #######################################################################


def tension_template():
    """What a valid proposal needs (constitution 5.3.1)"""
    return (
        "\n\n".join(
            f"## {heading}\n\n"
            for heading in [
                gettext("The tension from the point of view of the role"),
                gettext("An example of a past or current situation"),
                gettext("How the proposal addresses the tension in the example"),
            ]
        ).strip()
        + "\n"
    )


class TensionForm(ModelForm):
    class Meta:
        model = Proposal
        fields = ["role", "tension"]
        widgets = {"tension": forms.Textarea(attrs={"rows": 12})}

    def __init__(self, *args, roles, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].queryset = roles
        self.fields["role"].required = True
        # New ones: the proposer chooses, none is preselected
        empty = [] if self.instance.role_id else [("", "---------")]
        roles = list(roles)
        groups = [
            (_("Roles"), [(r.pk, str(r)) for r in roles if not r.core_role]),
            (_("Core roles"), [(r.pk, str(r)) for r in roles if r.core_role]),
        ]
        self.fields["role"].choices = empty + [g for g in groups if g[1]]
        self.fields["role"].label = _("From my role")
        self.fields["tension"].required = True
        self.fields["tension"].help_text = _(
            "What is the gap between what is and what could be? Without"
            " changes the draft stays a tension, visible only to you."
        )


def changed_meanwhile(pending, paths, current, proposed):
    """Whether the field changed since the proposal was drafted (e.g. by a
    proposal adopted earlier in the meeting) and the proposal changes it
    differently: the secretary merges both"""
    current = current or ""
    return any(
        instruction["path"] in paths
        and instruction.get("original_value") is not None
        and instruction["original_value"] != current
        and (proposed or "") != current
        for instruction in pending
    )


MERGE_NOTE = _(
    "Changed in the meantime: merge the current text and the proposal's,"
    " and remove the lines with <<<<<<<, ======= and >>>>>>>."
)


def conflict(label, current, proposed):
    """Both versions between Git's conflict markers"""
    return "\n".join([
        f"<<<<<<< {label}",
        *([current] if current else []),
        "=======",
        *([proposed] if proposed else []),
        f">>>>>>> {gettext('proposal')}",
    ])


class MergeMixin:
    """Fields changed in the meantime: text areas start with both versions
    between conflict markers, which have to go before saving; single-line
    fields show the current value and need a confirmation"""

    def merge(self, name, current, proposed):
        field = self.fields[name]
        if isinstance(field.widget, forms.Textarea):
            self.initial[name] = conflict(gettext("currently"), current, proposed)
            note = MERGE_NOTE
        else:
            note = _("Changed in the meantime, currently: %(value)s") % {
                "value": current or "–"
            }
            fields = list(self.fields.items())
            fields.insert(
                [key for key, _field in fields].index(name) + 1,
                (
                    f"{name}_merged",
                    forms.BooleanField(
                        label=_("I've merged it with the current value."),
                        required=True,
                    ),
                ),
            )
            self.fields = dict(fields)
        self.add_note(field, note)

    def orphaned(self, name, texts):
        """The proposal changes texts removed in the meantime: they're
        offered as new ones, kept or dropped by removing the markers"""
        field = self.fields[name]
        self.initial[name] = "\n".join([
            *([field.initial] if field.initial else []),
            *(conflict(gettext("removed in the meantime"), "", text) for text in texts),
        ])
        self.add_note(field, MERGE_NOTE)

    def add_note(self, field, note):
        # Help texts aren't escaped
        field.help_text = (
            format_html("{} {}", field.help_text, note)
            if field.help_text
            else format_html("{}", note)
        )

    def check_markers(self, data):
        for name, value in list(data.items()):
            if isinstance(value, str) and MARKERS.search(value):
                self.add_error(
                    name, _("Merge both versions and remove the conflict markers.")
                )


def text_field(label, initial, *, required=False, rows=2, help_text=""):
    return forms.CharField(
        label=label,
        initial=initial,
        required=required,
        help_text=help_text,
        widget=forms.Textarea(attrs={"rows": rows}),
    )


class RoleForm(MergeMixin, Form):
    def __init__(self, *args, proposal, key, role, **kwargs):
        super().__init__(*args, **kwargs)
        self.role = role
        pending = instructions_of(proposal, f"roles/{key}")
        values = {"name": "", "purpose": ""}
        if role is not None:
            values = {"name": role.name, "purpose": role.purpose}
        values |= {
            {"name": "name", "aim": "purpose"}[i["path"].rsplit("/", 1)[1]]: i.get(
                "value"
            )
            or ""
            for i in pending
            if i["path"] in {f"/roles/{key}/name", f"/roles/{key}/aim"}
        }
        if role is None or not role.core_role:
            self.fields["name"] = forms.CharField(
                label=_("Name"), initial=values["name"], max_length=200
            )
            self.fields["purpose"] = text_field(_("Purpose"), values["purpose"])
            if role is not None:
                for field, path in [("name", "name"), ("purpose", "aim")]:
                    current = getattr(role, field)
                    if changed_meanwhile(
                        pending, {f"/roles/{key}/{path}"}, current, values[field]
                    ):
                        self.merge(field, current, values[field])
        for kind, label, new_label in TEXT_KINDS:
            existing = getattr(role, kind).all() if role is not None else []
            for obj in existing:
                text = obj.text
                for i in pending:
                    if i["path"] in {
                        f"/roles/{key}/{kind}/{obj.pk}",
                        f"/roles/{key}/{kind}/{obj.pk}/description",
                    }:
                        text = "" if i["op"] == "remove" else i.get("value") or ""
                paths = {
                    f"/roles/{key}/{kind}/{obj.pk}",
                    f"/roles/{key}/{kind}/{obj.pk}/description",
                }
                self.fields[f"{kind}-{obj.pk}"] = text_field(
                    label, text, help_text=_("Empty to remove.")
                )
                if changed_meanwhile(pending, paths, obj.text, text):
                    self.merge(f"{kind}-{obj.pk}", obj.text, text)
            self.fields[f"new_{kind}"] = text_field(
                new_label,
                "\n".join(
                    i.get("value") or ""
                    for i in pending
                    if i["op"] == "add"
                    and i["path"].startswith(f"/roles/{key}/{kind}/n")
                ),
                rows=3,
                help_text=_("One per line."),
            )
            # Changes of texts removed in the meantime (removing them again
            # needs nothing)
            known = {str(obj.pk) for obj in existing}
            if orphans := [
                i.get("value") or ""
                for i in pending
                if i["op"] == "replace"
                and (
                    match := re.fullmatch(
                        rf"/roles/{key}/{kind}/(\d+)(?:/description)?", i["path"]
                    )
                )
                and match[1] not in known
            ]:
                self.orphaned(f"new_{kind}", orphans)

    def clean(self):
        data = super().clean()
        for name, value in list(data.items()):
            if isinstance(value, str):
                data[name] = value.replace("\r\n", "\n").strip()
        self.check_markers(data)
        return data


class PolicyForm(MergeMixin, Form):
    title = forms.CharField(label=_("Title"), max_length=200)
    body = forms.CharField(
        label=_("Text"), widget=forms.Textarea(attrs={"rows": 8}), required=False
    )

    def clean(self):
        data = super().clean()
        data["body"] = data.get("body", "").replace("\r\n", "\n").strip()
        self.check_markers(data)
        return data


# Views #######################################################################


def can_edit(user, proposal):
    """The proposer edits drafts, the secretary amends in a meeting"""
    if proposal.status == Proposal.DRAFT:
        return proposal.proposer_id == user.pk
    meeting = proposal.meeting
    return (
        proposal.status == Proposal.IN_MEETING
        and meeting is not None
        and meeting.is_running
        and meeting.secretary_id == user.pk
    )


def editable_proposal(request, pk):
    proposal = get_object_or_404(
        Proposal.objects.visible_to(request.user).select_related("circle", "meeting"),
        pk=pk,
    )
    if not can_edit(request.user, proposal):
        raise PermissionDenied
    return proposal


def proposal_create(request, pk):
    circle = get_object_or_404(Role.objects.active().with_inside(), pk=pk)
    roles = proposer_roles(request.user, circle)
    if not roles.exists():
        # Proposals address tensions of the proposer's roles in the circle
        raise PermissionDenied
    form = TensionForm(
        request.POST or None, roles=roles, initial={"tension": tension_template()}
    )
    if form.is_valid():
        form.instance.circle = circle
        form.instance.proposer = request.user
        form.instance.created_at = timezone.now()
        proposal = form.save()
        return redirect(proposal)
    return render(
        request,
        "generic/object_form.html",
        {
            "title": gettext("New proposal in %(circle)s") % {"circle": circle},
            "form": form,
            "cancel_url": circle.get_absolute_url(),
            # The changes are added on the draft's page afterwards
            "submit_label": gettext("Continue"),
        },
    )


def proposal_update(request, pk):
    proposal = editable_proposal(request, pk)
    # The proposer's roles (also in a meeting, where the secretary edits)
    roles = Role.objects.filter(pk=proposal.role_id)
    if proposal.proposer:
        roles = (proposer_roles(proposal.proposer, proposal.circle) | roles).distinct()
    form = TensionForm(request.POST or None, instance=proposal, roles=roles)
    if form.is_valid():
        form.save()
        return done(request, proposal)
    return render(
        request,
        "generic/object_form.html",
        {
            "title": gettext("Edit the tension"),
            "form": form,
            "cancel_url": cancel_url(request, proposal),
        },
    )


@require_POST
def proposal_delete(request, pk):
    proposal = editable_proposal(request, pk)
    if proposal.status != Proposal.DRAFT:
        raise PermissionDenied
    circle = proposal.circle
    proposal.delete()
    messages.success(request, gettext("The draft has been deleted."))
    return redirect(circle)


def get_role(proposal, key):
    if NEW_KEY.fullmatch(key):
        if not instructions_of(proposal, f"roles/{key}"):
            raise PermissionDenied
        return None
    circle = proposal.circle
    return get_object_or_404(
        Role.objects.active().filter(
            # The anchor circle's own definition is changed in its governance
            Q(circle=circle) | Q(pk=circle.pk, circle=None)
        ),
        pk=key,
    )


def get_policy(proposal, key):
    if NEW_KEY.fullmatch(key):
        if not instructions_of(proposal, f"policies/{key}"):
            raise PermissionDenied
        return None
    # Not the policies of its roles for their domains, they change them
    # themselves (1.3.2)
    return get_object_or_404(
        Policy.objects.active().filter(role=proposal.circle), pk=key
    )


def role_edit(request, pk, key=None):
    proposal = editable_proposal(request, pk)
    is_existing = key is not None
    key = key or new_key(proposal.instructions)
    role = get_role(proposal, key) if is_existing else None
    if role is not None and role.core_role == LEAD:
        raise PermissionDenied  # Stays as the constitution defines it
    form = RoleForm(request.POST or None, proposal=proposal, key=key, role=role)
    if form.is_valid():
        new = role_instructions(proposal, key, role, form.cleaned_data)
        replace_subject(proposal, f"roles/{key}", new)
        name = form.cleaned_data.get("name") or (role and role.name)
        proposal.names[f"roles/{key}"] = role.name if role else name
        proposal.save(update_fields=["instructions", "names"])
        return done(request, proposal)
    return render(
        request,
        "generic/object_form.html",
        {
            "title": gettext("Change %(role)s") % {"role": role}
            if role
            else gettext("New role in %(circle)s") % {"circle": proposal.circle},
            "form": form,
            "cancel_url": cancel_url(request, proposal),
        },
    )


def policy_edit(request, pk, key=None):
    proposal = editable_proposal(request, pk)
    is_existing = key is not None
    if not is_existing and not proposal.circle.is_circle:
        raise PermissionDenied  # Only policies for its domains (1.3.2)
    key = key or new_key(proposal.instructions)
    policy = get_policy(proposal, key) if is_existing else None
    values = proposed_values(
        proposal, f"policies/{key}", policy, [("title", "title"), ("body", "body")]
    )
    form = PolicyForm(request.POST or None, initial=values)
    if policy is not None:
        pending = instructions_of(proposal, f"policies/{key}")
        for field in ["title", "body"]:
            current = getattr(policy, field)
            if changed_meanwhile(
                pending, {f"/policies/{key}/{field}"}, current, values[field]
            ):
                form.merge(field, current, values[field])
    if form.is_valid():
        replace_subject(
            proposal,
            f"policies/{key}",
            policy_instructions(key, policy, form.cleaned_data),
        )
        proposal.names[f"policies/{key}"] = (
            policy.title if policy else form.cleaned_data["title"]
        )
        proposal.save(update_fields=["instructions", "names"])
        return done(request, proposal)
    return render(
        request,
        "generic/object_form.html",
        {
            "title": gettext("Change %(policy)s") % {"policy": policy}
            if policy
            else gettext("New policy in %(circle)s") % {"circle": proposal.circle},
            "form": form,
            "cancel_url": cancel_url(request, proposal),
        },
    )


@require_POST
def subject_remove(request, pk, kind, key):
    """Proposes to remove the role or policy"""
    if kind not in {"roles", "policies"}:
        raise PermissionDenied
    proposal = editable_proposal(request, pk)
    obj = (get_role if kind == "roles" else get_policy)(proposal, key)
    if obj is None:  # Added by this proposal: undo instead
        return subject_undo(request, pk, kind, key)
    replace_subject(
        proposal,
        f"{kind}/{key}",
        [
            {"op": "test", "path": f"/{kind}/{key}"},
            {"op": "remove", "path": f"/{kind}/{key}"},
        ],
        managed_only=False,
    )
    proposal.names[f"{kind}/{key}"] = str(obj)
    proposal.save(update_fields=["instructions", "names"])
    return done(request, proposal)


class CircleRemoveForm(Form):
    def __init__(self, *args, circle, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["roles"] = forms.ModelMultipleChoiceField(
            label=_("Roles to move to %(circle)s") % {"circle": circle.circle},
            queryset=circle.roles
            .active()
            .exclude(core_role__in=CORE_ROLES)
            .order_by("position", "name"),
            widget=forms.CheckboxSelectMultiple,
            required=False,
        )
        self.fields["policies"] = forms.ModelMultipleChoiceField(
            label=_("Policies to move to %(circle)s") % {"circle": circle.circle},
            queryset=circle.policies.active(),
            widget=forms.CheckboxSelectMultiple,
            required=False,
        )


def circle_remove(request, pk, key):
    """Removes a circle: the selected roles and policies move to the
    super-circle, everything else is removed with it"""
    proposal = editable_proposal(request, pk)
    circle = get_role(proposal, key)
    if circle is None or not circle.is_circle or circle.circle_id is None:
        raise PermissionDenied
    source = f"/circles/{circle.pk}/"
    # What the proposal moves out of the circle already (also with the
    # form moving roles and policies): saving replaces those moves
    initial = {"roles": [], "policies": []}
    for instruction in proposal.instructions:
        if instruction["op"] == "move" and (
            match := re.fullmatch(
                rf"{source}(roles|policies)/(\d+)", instruction.get("from", "")
            )
        ):
            initial[match[1]].append(int(match[2]))
    form = CircleRemoveForm(request.POST or None, circle=circle, initial=initial)
    if form.is_valid():
        moves = [
            {
                "op": "move",
                "path": f"/{kind}/{obj.pk}",
                "from": f"{source}{kind}/{obj.pk}",
            }
            for kind in ["roles", "policies"]
            for obj in form.cleaned_data[kind]
        ]
        for kind in ["roles", "policies"]:
            for obj in form.cleaned_data[kind]:
                proposal.names[f"{kind}/{obj.pk}"] = str(obj)
        proposal.instructions = [
            i for i in proposal.instructions if not i.get("from", "").startswith(source)
        ]
        replace_subject(
            proposal,
            f"roles/{key}",
            [
                *moves,
                {"op": "test", "path": f"/roles/{key}"},
                {"op": "remove", "path": f"/roles/{key}"},
            ],
            managed_only=False,
        )
        proposal.names[f"roles/{key}"] = proposal.names[f"circles/{key}"] = str(circle)
        proposal.save(update_fields=["instructions", "names"])
        return done(request, proposal)
    return render(
        request,
        "generic/object_form.html",
        {
            "title": gettext("Remove %(circle)s") % {"circle": circle},
            "form": form,
            "cancel_url": cancel_url(request, proposal),
            "submit_label": gettext("Remove the circle"),
            "help": gettext(
                "The selected roles and policies move to %(circle)s. Everything"
                " else is removed with the circle, also its sub-circles, and"
                " their assignments end."
            )
            % {"circle": circle.circle},
        },
    )


@require_POST
def role_convert(request, pk, key):
    """Proposes to turn the role into a circle, or the circle into a role"""
    proposal = editable_proposal(request, pk)
    role = get_role(proposal, key)
    if role is None or role.core_role:
        raise PermissionDenied
    path = f"/roles/{key}/supporting_circle"
    pending = [i for i in proposal.instructions if i["path"] == path]
    if pending:
        proposal.instructions = normalize([
            i for i in proposal.instructions if i["path"] != path
        ])
    else:
        proposal.instructions = normalize([
            *proposal.instructions,
            {"op": "test", "path": f"/roles/{key}"},
            {"op": "remove" if role.is_circle else "add", "path": path},
        ])
        proposal.names[f"roles/{key}"] = role.name
    proposal.save(update_fields=["instructions", "names"])
    return done(request, proposal)


@require_POST
def subject_undo(request, pk, kind, key):
    """Drops the proposal's changes of a role or policy"""
    if kind not in {"roles", "policies"}:
        raise PermissionDenied
    proposal = editable_proposal(request, pk)
    replace_subject(proposal, f"{kind}/{key}", [], managed_only=False)
    proposal.names.pop(f"{kind}/{key}", None)
    proposal.save(update_fields=["instructions", "names"])
    return done(request, proposal)


def sub_circles_of(circle):
    """The sub-circles and any sub-circles thereof (5.2), depth-first, with
    their path from the circle (``label``) and the circles containing them
    (``ancestor_pks``)"""
    circles = Role.objects.depth_first()
    by_pk = {c.pk: c for c in circles}
    result = []
    for sub in circles:
        path, parent = [sub], by_pk.get(sub.circle_id)
        while parent is not None and parent.pk != circle.pk:
            path.insert(0, parent)
            parent = by_pk.get(parent.circle_id)
        if parent is None:
            continue  # Not inside the circle
        sub.label = " › ".join(c.name for c in path)
        sub.ancestor_pks = [c.pk for c in path[:-1]]
        result.append(sub)
    return result


def movable(circle):
    """Roles and policies of the circle and of its sub-circles (also any
    sub-circles thereof, 5.2)"""
    sub_circles = sub_circles_of(circle)
    for sub in sub_circles:
        sub.movable_roles = sub.roles.active().filter(core_role="").order_by("name")
        sub.movable_policies = Policy.objects.active().filter(role=sub)
    deeper = [sub for sub in sub_circles if sub.circle_id != circle.pk]
    roles = list(circle.roles.active().filter(core_role="").order_by("name"))
    for role in roles:
        role.ancestor_pks = []
    return {
        "sub_circles": sub_circles,
        # Moving roles into a role makes it a circle; deeper only circles
        "targets": [*roles, *deeper],
        "roles": circle.roles.active().filter(core_role="").order_by("name"),
        "policies": Policy.objects.active().filter(role=circle),
    }


def proposal_move(request, pk):
    """Moving roles and policies into a sub-circle or out of one"""
    proposal = editable_proposal(request, pk)
    circle = proposal.circle
    context = movable(circle)
    if request.method == "POST":
        kind = request.POST.get("kind")
        if kind not in {"roles", "policies"}:
            raise PermissionDenied
        model = Role if kind == "roles" else Policy
        obj = get_object_or_404(model.objects.active(), pk=request.POST.get("key"))
        subs = {str(sub.pk): sub for sub in context["sub_circles"]}
        targets = {str(target.pk): target for target in context["targets"]}
        if kind == "policies":
            targets = subs  # Policies only go to circles
        owner = obj.circle_id if kind == "roles" else obj.role_id
        if owner == circle.pk:
            target = targets.get(request.POST.get("target", ""))
            if (
                target is None
                or target == obj
                # Not into its own inside
                or obj.pk in getattr(target, "ancestor_pks", ())
            ):
                raise PermissionDenied
            new = [
                {"op": "test", "path": f"/{kind}/{obj.pk}"},
                {
                    "op": "move",
                    "path": f"/roles/{target.pk}/supporting_circle/{kind}/{obj.pk}",
                    "from": f"/{kind}/{obj.pk}",
                },
            ]
            proposal.names[f"roles/{target.pk}"] = target.name
        elif (source := subs.get(str(owner))) is not None:
            new = [
                {
                    "op": "move",
                    "path": f"/{kind}/{obj.pk}",
                    "from": f"/circles/{source.pk}/{kind}/{obj.pk}",
                }
            ]
            proposal.names[f"circles/{source.pk}"] = source.name
        else:
            raise PermissionDenied
        key = f"{kind}/{obj.pk}"
        proposal.instructions = [
            i
            for i in proposal.instructions
            if not (subject_of(i["path"]) == key and i["op"] == "move")
        ]
        # The proposal's changes of it apply before it moves away (they're
        # checked against the circle)
        replace_subject(proposal, key, instructions_of(proposal, key) + new)
        proposal.names[key] = str(obj)
        proposal.save(update_fields=["instructions", "names"])
        return done(request, proposal)
    return render(
        request,
        "proposals/proposal_move.html",
        context | {"proposal": proposal, "circle": circle},
    )
