"""Reading circles and roles, see section 8 of SPEC.md"""

import copy

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Router, Schema
from ninja.errors import HttpError

from governance.history.update import update_today
from governance.roles.context import affecting
from governance.roles.editing import can_edit_items, next_position
from governance.roles.export import governance_markdown
from governance.roles.models import (
    FREQUENCY_CHOICES,
    Assignment,
    ChecklistItem,
    Domain,
    Link,
    Metric,
    Note,
    Policy,
    Role,
)
from governance.search import search_results


router = Router(tags=["roles"])


def absolute(obj):
    """The URL of the object's page, the CLI links to it"""
    return settings.BASE_URL + obj.get_absolute_url()


class CircleOut(Schema):
    id: int
    name: str
    circle_id: int | None
    depth: int
    purpose: str
    url: str


class TextOut(Schema):
    id: int | None  # None: the constitution's, of core roles
    text: str


class PolicyOut(Schema):
    id: int
    title: str
    body: str
    role_id: int
    domain_id: int | None
    url: str

    @staticmethod
    def resolve_url(obj):
        return absolute(obj)


class RoleLeadOut(Schema):
    user_id: int
    name: str
    focus: str
    elected_until: str | None
    url: str


class RoleSummaryOut(Schema):
    id: int
    name: str
    core_role: str
    is_circle: bool
    url: str

    @staticmethod
    def resolve_url(obj):
        return absolute(obj)


class LinkOut(Schema):
    id: int
    role_id: int
    title: str
    url: str
    description: str


class NoteOut(Schema):
    id: int
    role_id: int
    title: str
    # Markdown
    body: str
    # Opens it on the role's page
    url: str

    @staticmethod
    def resolve_url(obj):
        return f"{absolute(obj.role)}#note-{obj.pk}"


class ItemOut(Schema):
    """A metric or checklist item"""

    id: int
    role_id: int
    role: str
    # A circle's own item, reported by the whole circle in its own tactical
    # meetings; else the role (a sub-circle too) reports it in its circle's
    whole_circle: bool
    # The circle whose tactical meetings review it
    reported_in_id: int | None
    description: str
    # weekly, monthly, quarterly, yearly or empty
    frequency: str
    link: str

    @staticmethod
    def resolve_role(obj):
        return obj.role.name

    @staticmethod
    def resolve_reported_in_id(obj):
        circle = obj.reported_in
        return circle.pk if circle else None


class RoleOut(Schema):
    id: int
    name: str
    circle_id: int | None
    is_circle: bool
    core_role: str
    purpose: str
    strategy: str
    short_name: str
    other_names: list[str]
    accountabilities: list[TextOut]
    domains: list[TextOut]
    policies: list[PolicyOut]
    role_leads: list[RoleLeadOut]
    roles: list[RoleSummaryOut]
    # To external tools, e.g. where the projects are managed
    links: list[LinkOut]
    # What helps doing the role's work, in Markdown
    notes: list[NoteOut]
    # Its own, not those of a circle's roles
    metrics: list[ItemOut]
    checklist_items: list[ItemOut]
    url: str


class FoundTextOut(Schema):
    """An accountability or domain, with its role"""

    id: int | None  # None: the constitution's, of core roles
    text: str
    role_id: int
    role: str
    url: str


class PersonFoundOut(Schema):
    id: int
    name: str
    url: str
    # Whose roles the person holds
    circles: list[RoleSummaryOut]

    @staticmethod
    def resolve_name(obj):
        return str(obj)

    @staticmethod
    def resolve_url(obj):
        return absolute(obj)


class FoundLinkOut(Schema):
    """A link, with the role keeping it"""

    id: int
    title: str
    url: str
    description: str
    role_id: int
    role: str
    role_url: str


class FoundNoteOut(Schema):
    """A note, with the role keeping it; the URL opens it on the role's page"""

    id: int
    title: str
    body: str
    role_id: int
    role: str
    url: str


class SearchOut(Schema):
    people: list[PersonFoundOut]
    roles: list[RoleSummaryOut]
    accountabilities: list[FoundTextOut]
    domains: list[FoundTextOut]
    policies: list[PolicyOut]
    links: list[FoundLinkOut]
    notes: list[FoundNoteOut]


@router.get("circles/", response=list[CircleOut])
def circles(request):
    """The circles in the organization's order (depth-first)"""
    return [
        {
            "id": circle.pk,
            "name": circle.name,
            "circle_id": circle.circle_id,
            "depth": circle.depth,
            "purpose": str(circle.display_purpose),
            "url": absolute(circle),
        }
        for circle in Role.objects.depth_first()
    ]


class MentionOut(Schema):
    id: int
    name: str
    circle: str


@router.get("roles/", response=list[MentionOut])
def roles(request):
    """The active roles with their circle, e.g. for autocompleting mentions"""
    return [
        {"id": role.pk, "name": role.name, "circle": str(role.circle or "")}
        for role in Role.objects
        .active()
        .select_related("circle")
        .order_by("name", "circle__name")
    ]


@router.get("roles/{int:pk}/", response=RoleOut)
def role(request, pk: int):
    """A role or circle with its texts, policies, Role Leads and roles"""
    role = get_object_or_404(Role, pk=pk)

    def constitutional(kind):
        texts = getattr(role.core, kind) if role.core else []
        return [{"id": None, "text": str(text)} for text in texts]

    return {
        "id": role.pk,
        "name": role.name,
        "circle_id": role.circle_id,
        "is_circle": role.is_circle,
        "core_role": role.core_role,
        "purpose": str(role.display_purpose),
        "strategy": role.strategy,
        "short_name": role.short_name,
        "other_names": role.other_names,
        "accountabilities": constitutional("accountabilities")
        + [{"id": a.pk, "text": a.text} for a in role.accountabilities.all()],
        "domains": constitutional("domains")
        + [{"id": d.pk, "text": d.text} for d in role.domains.all()],
        "policies": list(role.policies.active()),
        "role_leads": [
            {
                "user_id": a.user_id,
                "name": str(a.user),
                "focus": a.focus,
                "elected_until": a.elected_until.isoformat()
                if a.elected_until
                else None,
                "url": absolute(a.user),
            }
            for a in Assignment.objects
            .current()
            .filter(role=role)
            .select_related("user")
        ],
        "roles": list(role.roles.active().order_by("position", "name"))
        if role.is_circle
        else [],
        "links": list(role.links.all()),
        "notes": list(role.notes.select_related("role")),
        "metrics": list(role.metrics.select_related("role__circle")),
        "checklist_items": list(role.checklistitems.select_related("role__circle")),
        "url": absolute(role),
    }


class LinkIn(Schema):
    title: str
    url: str
    description: str = ""


class LinkPatch(Schema):
    title: str | None = None
    url: str | None = None
    description: str | None = None


def editable(request, item):
    """Anybody edits the links and notes of active roles, like on the pages"""
    if not can_edit_items(request.user, item.role, type(item)):
        raise HttpError(403, "The role is archived.")
    return item


def save_item(item, data):
    for field, value in data.items():
        setattr(item, field, value.strip())
    try:
        item.full_clean()
    except ValidationError as exc:
        raise HttpError(
            400, " ".join(f"{f}: {' '.join(e)}" for f, e in exc.message_dict.items())
        ) from exc
    item.save()
    update_today()  # The history shows them on request
    return item


def existing(request, model, pk):
    return editable(
        request, get_object_or_404(model.objects.select_related("role"), pk=pk)
    )


@router.post("roles/{int:pk}/links/", response=LinkOut)
def link_create(request, pk: int, data: LinkIn):
    """A link of the role or circle, after its links and notes"""
    role = get_object_or_404(Role, pk=pk)
    link = editable(request, Link(role=role, position=next_position(role, Link)))
    return save_item(link, data.dict())


@router.patch("links/{int:pk}/", response=LinkOut)
def link_update(request, pk: int, data: LinkPatch):
    return save_item(existing(request, Link, pk), data.dict(exclude_none=True))


@router.delete("links/{int:pk}/", response=LinkOut)
def link_delete(request, pk: int):
    """Returns the deleted link"""
    link = existing(request, Link, pk)
    out = {field: getattr(link, field) for field in LinkOut.model_fields}
    link.delete()
    update_today()
    return out


class NoteIn(Schema):
    title: str
    body: str = ""


class NotePatch(Schema):
    title: str | None = None
    body: str | None = None


@router.post("roles/{int:pk}/notes/", response=NoteOut)
def note_create(request, pk: int, data: NoteIn):
    """A note of the role or circle, after its links and notes"""
    role = get_object_or_404(Role, pk=pk)
    note = editable(request, Note(role=role, position=next_position(role, Note)))
    return save_item(note, data.dict())


@router.patch("notes/{int:pk}/", response=NoteOut)
def note_update(request, pk: int, data: NotePatch):
    return save_item(existing(request, Note, pk), data.dict(exclude_none=True))


@router.delete("notes/{int:pk}/", response=NoteOut)
def note_delete(request, pk: int):
    """Returns the deleted note"""
    note = existing(request, Note, pk)
    # Deleting clears the instance's ID, not the copy's
    out = copy.copy(note)
    note.delete()
    update_today()
    return out


class ItemIn(Schema):
    description: str
    frequency: str = ""
    link: str = ""
    whole_circle: bool = False


class ItemPatch(Schema):
    description: str | None = None
    frequency: str | None = None
    link: str | None = None
    # Another role reports it (its ID)
    role_id: int | None = None
    whole_circle: bool | None = None


ITEM_MODELS = {"metrics": Metric, "checklist": ChecklistItem}


def item_model(kind):
    if kind not in ITEM_MODELS:
        raise HttpError(404, "Not found: metrics or checklist.")
    return ITEM_MODELS[kind]


def save_role_item(request, item, data):
    """Metrics need the Circle Leads of the circle reviewing them, before and
    after; only circles have items of the whole circle"""
    if (role_id := data.pop("role_id", None)) is not None:
        item.role = get_object_or_404(Role.objects.active(), pk=role_id)
    if (whole := data.pop("whole_circle", None)) is not None:
        item.whole_circle = whole
    if item.whole_circle != item.role.is_circle and not item.role.circle_id:
        raise HttpError(400, "The anchor circle's items are the whole circle's.")
    if item.whole_circle and not item.role.is_circle:
        raise HttpError(400, "whole_circle: only for circles.")
    if data.get("frequency", "") not in {"", *dict(FREQUENCY_CHOICES)}:
        raise HttpError(
            400, f"frequency: one of {', '.join(dict(FREQUENCY_CHOICES))} or empty."
        )
    if not can_edit_items(
        request.user, item.role, type(item), whole_circle=item.whole_circle
    ):
        raise HttpError(403, "Not allowed for this role.")
    return save_item(item, data)


def item_create(request, pk, model, data):
    role = get_object_or_404(Role, pk=pk)
    item = model(role=role, position=next_position(role, model))
    return save_role_item(request, item, data.dict())


@router.post("roles/{int:pk}/metrics/", response=ItemOut)
def metric_create(request, pk: int, data: ItemIn):
    """A metric of the role or circle"""
    return item_create(request, pk, Metric, data)


@router.post("roles/{int:pk}/checklist/", response=ItemOut)
def checklist_item_create(request, pk: int, data: ItemIn):
    """A checklist item of the role or circle"""
    return item_create(request, pk, ChecklistItem, data)


def existing_item(request, kind, pk):
    item = get_object_or_404(item_model(kind).objects.select_related("role"), pk=pk)
    if not can_edit_items(
        request.user, item.role, type(item), whole_circle=item.whole_circle
    ):
        raise HttpError(403, "Not allowed for this role.")
    return item


@router.patch("items/{kind}/{int:pk}/", response=ItemOut)
def item_update(request, kind: str, pk: int, data: ItemPatch):
    item = existing_item(request, kind, pk)
    return save_role_item(request, item, data.dict(exclude_none=True))


@router.delete("items/{kind}/{int:pk}/", response=ItemOut)
def item_delete(request, kind: str, pk: int):
    """Returns the deleted metric or checklist item"""
    item = existing_item(request, kind, pk)
    out = copy.copy(item)
    item.delete()
    update_today()
    return out


@router.get("search/", response=SearchOut)
def search(request, q: str):
    """All terms have to match, ignoring case and accents"""
    results = search_results(q) or {
        "people": [],
        "roles": [],
        "accountabilities": [],
        "domains": [],
        "policies": [],
        "links": [],
        "notes": [],
    }

    def found(item):
        return {
            "id": item.pk,
            "text": item.text,
            "role_id": item.role_id,
            "role": item.role.name,
            "url": absolute(item.role),
        }

    return {
        **results,
        "accountabilities": [found(a) for a in results["accountabilities"]],
        "domains": [found(d) for d in results["domains"]],
        "links": [
            {
                "id": link.pk,
                "title": link.title,
                "url": link.url,
                "description": link.description,
                "role_id": link.role_id,
                "role": link.role.name,
                "role_url": absolute(link.role),
            }
            for link in results["links"]
        ],
        "notes": [
            {
                "id": note.pk,
                "title": note.title,
                "body": note.body,
                "role_id": note.role_id,
                "role": note.role.name,
                "url": f"{absolute(note.role)}#note-{note.pk}",
            }
            for note in results["notes"]
        ],
    }


class PolicyDetailOut(Schema):
    id: int
    title: str
    body: str
    # The circle, or a role for its domains
    role_id: int
    role: str
    circle_id: int | None
    circle: str
    domain_id: int | None
    domain: str
    url: str


def policy_out(policy):
    circle = policy.role.governing_circle
    return {
        "id": policy.pk,
        "title": policy.title,
        "body": policy.body,
        "role_id": policy.role_id,
        "role": policy.role.name,
        "circle_id": circle.pk if circle else None,
        "circle": circle.name if circle else "",
        "domain_id": policy.domain_id,
        "domain": policy.domain.text if policy.domain else "",
        "url": absolute(policy),
    }


@router.get("policies/", response=list[PolicyDetailOut])
def policies(request, circle_id: int | None = None):
    """The active policies in the organization's order: a circle's own,
    then those of its roles for their domains"""
    order = {c.pk: index for index, c in enumerate(Role.objects.depth_first())}
    queryset = Policy.objects.active().select_related("role__circle", "domain")
    if circle_id:
        queryset = queryset.filter(
            Q(role=circle_id) | Q(role__circle=circle_id, role__is_circle=False)
        )
    return [
        policy_out(policy)
        for policy in sorted(
            queryset,
            key=lambda p: (
                order.get(p.role.governing_circle_id, -1),
                not p.role.is_circle,
                p.role.name,
                p.position,
                p.title,
            ),
        )
    ]


@router.get("policies/{int:pk}/", response=PolicyDetailOut)
def policy(request, pk: int):
    """A policy with its text, archived ones too"""
    return policy_out(
        get_object_or_404(
            Policy.objects.select_related("role__circle", "domain"), pk=pk
        )
    )


class DomainPolicyOut(Schema):
    id: int
    title: str
    url: str

    @staticmethod
    def resolve_url(obj):
        return absolute(obj)


class DomainOut(Schema):
    id: int
    text: str
    role_id: int
    role: str
    circle_id: int | None
    circle: str
    # Domains have no page of their own, the role's
    url: str
    # The role's policies for the domain
    policies: list[DomainPolicyOut]


@router.get("domains/", response=list[DomainOut])
def domains(request, circle_id: int | None = None):
    """The domains of the active roles in the organization's order: a
    circle's own, then those of its roles"""
    order = {c.pk: index for index, c in enumerate(Role.objects.depth_first())}
    queryset = (
        Domain.objects
        .filter(role__archived_on=None)
        .select_related("role__circle")
        .prefetch_related(
            Prefetch("policies", queryset=Policy.objects.active(), to_attr="active")
        )
    )
    if circle_id:
        queryset = queryset.filter(Q(role=circle_id) | Q(role__circle=circle_id))
    result = []
    for domain in sorted(
        queryset,
        key=lambda d: (
            order.get(d.role.governing_circle_id, -1),
            not d.role.is_circle,
            d.role.name,
            d.position,
            d.pk,
        ),
    ):
        circle = domain.role.governing_circle
        result.append({
            "id": domain.pk,
            "text": domain.text,
            "role_id": domain.role_id,
            "role": domain.role.name,
            "circle_id": circle.pk if circle else None,
            "circle": circle.name if circle else "",
            "url": absolute(domain.role),
            "policies": domain.active,
        })
    return result


class ContextDomainOut(Schema):
    id: int
    text: str
    # The role's policies for the domain
    policies: list[PolicyOut]

    @staticmethod
    def resolve_policies(obj):
        return obj.role_policies


class ContextRoleOut(Schema):
    id: int
    name: str
    url: str
    # The constitution's domains of core roles
    core_domains: list[str]
    domains: list[ContextDomainOut]


class ContextCircleOut(Schema):
    id: int
    name: str
    url: str
    domains: list[ContextDomainOut]
    # Those not for one of its domains
    policies: list[PolicyOut]
    roles: list[ContextRoleOut]


@router.get("roles/{int:pk}/context/", response=list[ContextCircleOut])
def role_context(request, pk: int):
    """What constrains the role from outside, like its page's context: per
    circle containing it, outermost first, the circle's domains and
    policies and the domains of its other roles with their policies"""
    role = get_object_or_404(Role.objects.select_related("circle"), pk=pk)
    return [
        {
            "id": entry["circle"].pk,
            "name": entry["circle"].name,
            "url": absolute(entry["circle"]),
            "domains": entry["domains"],
            "policies": entry["policies"],
            "roles": [
                {
                    "id": other["role"].pk,
                    "name": other["role"].name,
                    "url": absolute(other["role"]),
                    "core_domains": [str(text) for text in other["core_domains"]],
                    "domains": other["domains"],
                }
                for other in entry["roles"]
            ],
        }
        for entry in affecting(role)
    ]


class ExportOut(Schema):
    date: str
    markdown: str


@router.get("export/", response=ExportOut)
def export(request, *, people: bool = False):
    """The whole current governance as one Markdown document, like
    /export/governance.md; who holds the roles (people) only when asked for"""
    return {
        "date": timezone.localdate().isoformat(),
        "markdown": governance_markdown(with_people=people),
    }
