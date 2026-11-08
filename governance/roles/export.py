"""The whole current governance as one Markdown document"""

from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone

from governance.roles.mentions import MENTION
from governance.roles.models import Assignment, Role


def plain_mentions(text):
    from governance.roles.models import Role

    roles = Role.objects.in_bulk({int(m[2]) for m in MENTION.finditer(text or "")})
    return MENTION.sub(
        lambda m: f"@{roles[int(m[2])].name}" if int(m[2]) in roles else f"@{m[1]}",
        text or "",
    )


def governance_markdown(*, with_holders=False):
    """Who holds the roles only when asked for: personal data"""
    circles = Role.objects.depth_first()
    holders = {}
    if with_holders:
        for assignment in Assignment.objects.current().select_related("user"):
            holders.setdefault(assignment.role_id, []).append(assignment)
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
            role.export_holders = holders.get(role.pk, [])
            role.export_role_policies = (
                list(role.policies.active()) if role is not circle else []
            )
    text = render_to_string(
        "roles/governance.txt",
        {"circles": circles, "now": timezone.localtime(), "with_holders": with_holders},
    )
    return plain_mentions(text)


def export_markdown(request):
    response = HttpResponse(
        governance_markdown(with_holders=request.GET.get("holders") == "1"),
        content_type="text/markdown; charset=utf-8",
    )
    response["Content-Disposition"] = (
        f'attachment; filename="governance-{timezone.localdate():%Y-%m-%d}.md"'
    )
    return response
