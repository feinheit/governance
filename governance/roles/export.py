"""The whole current governance as one Markdown document, or as data"""

from collections import defaultdict

from django.conf import settings
from django.db.models import Prefetch
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone

from governance.roles.mentions import MENTION
from governance.roles.models import Assignment, Policy, Role


def plain_mentions(text):
    from governance.roles.models import Role

    roles = Role.objects.in_bulk({int(m[2]) for m in MENTION.finditer(text or "")})
    return MENTION.sub(
        lambda m: f"@{roles[int(m[2])].name}" if int(m[2]) in roles else f"@{m[1]}",
        text or "",
    )


def governance_markdown(*, with_people=False):
    """Who holds the roles only when asked for: personal data"""
    circles = Role.objects.depth_first()
    role_leads = {}
    if with_people:
        for assignment in Assignment.objects.current().select_related("user"):
            role_leads.setdefault(assignment.role_id, []).append(assignment)
    for circle in circles:
        circle.heading = "#" * min(circle.depth + 2, 5)
        circle.subheading = "#" * min(circle.depth + 3, 6)
        circle.export_roles = list(
            circle.roles
            .active()
            .filter(is_circle=False)
            .prefetch_related("accountabilities", "domains")
            .order_by("position", "name")
        )
        circle.export_policies = list(circle.policies.active())
        for role in [circle, *circle.export_roles]:
            role.export_role_leads = role_leads.get(role.pk, [])
            role.export_role_policies = (
                list(role.policies.active()) if role is not circle else []
            )
    text = render_to_string(
        "roles/governance.txt",
        {"circles": circles, "now": timezone.localtime(), "with_people": with_people},
    )
    return plain_mentions(text)


def export_markdown(request):
    response = HttpResponse(
        governance_markdown(with_people=request.GET.get("people") == "1"),
        content_type="text/markdown; charset=utf-8",
    )
    response["Content-Disposition"] = (
        f'attachment; filename="governance-{timezone.localdate():%Y-%m-%d}.md"'
    )
    return response


def governance_data(*, with_people=False):
    """The current governance as data (``gov export --json``): a tree from
    the anchor circle down, each role with everything belonging to it and
    a circle with its roles (``roles``);
    the Role Leads only when asked for. Mentions with the current names,
    like the Markdown"""
    names = dict(Role.objects.values_list("pk", "name"))

    def plain(text):
        return MENTION.sub(lambda m: f"@{names.get(int(m[2]), m[1])}", str(text or ""))

    def url(obj):
        return settings.BASE_URL + obj.get_absolute_url()

    def policy(p):
        return {
            "id": p.pk,
            "title": p.title,
            "body": plain(p.body),
            "url": url(p),
            "glassfrog_id": p.glassfrog_id,
        }

    def item(i):
        return {
            "id": i.pk,
            "description": plain(i.description),
            "frequency": i.frequency,
            "link": i.link,
        }

    role_leads = {}
    if with_people:
        for assignment in Assignment.objects.current().select_related("user"):
            role_leads.setdefault(assignment.role_id, []).append({
                "name": str(assignment.user),
                "email": assignment.user.email,
                "focus": assignment.focus,
                "elected_until": assignment.elected_until.isoformat()
                if assignment.elected_until
                else None,
            })

    entries, children = [], defaultdict(list)
    for role in (
        Role.objects
        .active()
        .order_by("position", "name")
        .prefetch_related(
            "accountabilities",
            "domains",
            Prefetch("policies", queryset=Policy.objects.active()),
            "metrics",
            "checklistitems",
            "links",
        )
    ):
        core = role.core
        policies = list(role.policies.all())
        entry = {
            "id": role.pk,
            "name": role.name,
            "short_name": role.short_name,
            "is_circle": role.is_circle,
            "core_role": role.core_role,
            "purpose": plain(role.display_purpose),
            "strategy": plain(role.strategy),
            "url": url(role),
            "glassfrog_id": role.glassfrog_id,
            # The constitution's texts of core roles have no ID
            "accountabilities": [
                {"id": None, "text": str(text)}
                for text in (core.accountabilities if core else [])
            ]
            + [
                {"id": a.pk, "text": plain(a.text)} for a in role.accountabilities.all()
            ],
            "domains": [
                {"id": None, "text": str(text), "policies": []}
                for text in (core.domains if core else [])
            ]
            + [
                {
                    "id": d.pk,
                    "text": plain(d.text),
                    "policies": [policy(p) for p in policies if p.domain_id == d.pk],
                }
                for d in role.domains.all()
            ],
            # A circle's own, not for one of its domains
            "policies": [policy(p) for p in policies if not p.domain_id],
            "metrics": [item(i) for i in role.metrics.all()],
            "checklist_items": [item(i) for i in role.checklistitems.all()],
            "links": [
                {"title": link.title, "url": link.url, "description": link.description}
                for link in role.links.all()
            ],
        }
        if with_people:
            entry["role_leads"] = role_leads.get(role.pk, [])
        if role.is_circle:
            entry["roles"] = children[role.pk]
        entries.append((role, entry))
    active = {role.pk for role, _entry in entries}
    roots = []
    for role, entry in entries:
        # The anchor circle (roles of archived circles too, if any)
        if role.circle_id in active:
            children[role.circle_id].append(entry)
        else:
            roots.append(entry)
    return {"date": timezone.localdate().isoformat(), "roles": roots}
