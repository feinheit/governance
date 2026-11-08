"""Reading circles and roles, see section 8 of SPEC.md"""

from django.conf import settings
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Router, Schema

from governance.roles.context import affecting
from governance.roles.export import governance_data, governance_markdown
from governance.roles.models import Assignment, Domain, Policy, Role
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
    url: str


class FoundTextOut(Schema):
    """An accountability or domain, with its role"""

    id: int | None  # None: the constitution's, of core roles
    text: str
    role_id: int
    role: str
    url: str


class SearchOut(Schema):
    roles: list[RoleSummaryOut]
    accountabilities: list[FoundTextOut]
    domains: list[FoundTextOut]
    policies: list[PolicyOut]


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
        "url": absolute(role),
    }


@router.get("search/", response=SearchOut)
def search(request, q: str):
    """All terms have to match, ignoring case and accents"""
    results = search_results(q) or {
        "roles": [],
        "accountabilities": [],
        "domains": [],
        "policies": [],
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


@router.get("export/json/")
def export_json(request, *, people: bool = False):
    """The current governance as data: the active roles by ID with
    everything belonging to them, the Role Leads only when asked for"""
    return governance_data(with_people=people)
