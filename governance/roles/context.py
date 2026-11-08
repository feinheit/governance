"""What constrains a role from outside (5.2.1, 1.3.2): the role's page
(``views.role_context``) and the API (``gov roles context``)"""

from django.db.models import Prefetch

from governance.roles.models import Policy


def with_policies(domains, policies):
    """The domains with their policies (``role_policies``)"""
    for domain in domains:
        domain.role_policies = [p for p in policies if p.domain_id == domain.pk]
    return domains


def affecting(role):
    """Per circle containing the role, from the outermost down, the
    circle's domains and policies and the domains of its other roles with
    their policies"""
    ancestors = role.ancestors()
    circles = []
    for circle, inner in zip(ancestors, [*ancestors[1:], role], strict=True):
        policies = list(circle.policies.active().select_related("domain"))
        roles = []
        # Not the circle on the way down, it follows with its own section,
        # nor the role itself
        for other in (
            circle.roles
            .active()
            .exclude(pk=inner.pk)
            .prefetch_related(
                "domains", Prefetch("policies", queryset=Policy.objects.active())
            )
            .order_by("position", "name")
        ):
            domains = list(other.domains.all())
            core_domains = other.core.domains if other.core else []
            if domains or core_domains:
                roles.append({
                    "role": other,
                    "core_domains": core_domains,
                    "domains": with_policies(domains, list(other.policies.all())),
                })
        circles.append({
            "circle": circle,
            "domains": with_policies(list(circle.domains.all()), policies),
            "policies": [p for p in policies if not p.domain_id],
            "roles": roles,
        })
    return circles
