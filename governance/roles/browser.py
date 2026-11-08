"""The circle browser: circles nested as circles, see section 7 of SPEC.md

A React island (``frontend/circles``) draws the tree with d3-hierarchy's
circle packing; the page also lists it, so it works without JavaScript.
"""

from collections import defaultdict

from django.shortcuts import render
from django.utils.translation import gettext

from governance.roles.constitution import LEAD
from governance.roles.models import Assignment, Role


def circle_tree(user=None):
    """The anchor circle with its roles and sub-circles, recursively

    Roles say whether they are elected and whether ``user`` holds them.
    """
    roles = list(
        Role.objects.active().select_related("circle").order_by("position", "name")
    )
    role_leads = defaultdict(list)
    mine = set()
    for role_id, user_id, name, email in (
        Assignment.objects
        .current()
        .filter(role__archived_on=None)
        .order_by("user__full_name")
        .values_list("role", "user", "user__full_name", "user__email")
    ):
        role_leads[role_id].append(name or email)
        if user is not None and user_id == user.pk:
            mine.add(role_id)
    children = defaultdict(list)
    for role in roles:
        children[role.circle_id].append(role)

    def node(role):
        data = {
            "id": role.pk,
            "name": role.name,
            "url": role.get_absolute_url(),
            "kind": "circle"
            if role.is_circle
            else ("core" if role.core_role else "role"),
            "role_leads": role_leads[role.pk],
        }
        if role.is_circle:
            data["mine"] = role.pk in mine  # Circle Lead or Rep there
        else:
            data["elected"] = role.is_elected
            data["lead"] = role.core_role == LEAD
            data["mine"] = role.pk in mine
            if not role_leads[role.pk]:
                data["unfilled"] = str(role.unfilled)
        if role.is_circle:
            data["children"] = [node(child) for child in children[role.pk]]
        return data

    anchor = next((r for r in children[None] if r.is_circle), None)
    return node(anchor) if anchor else None


def circle_browser(request):
    # The island's texts, translated here instead of a JavaScript catalog
    labels = {
        "Path": gettext("Path"),
        "Open the circle's page": gettext("Open the circle's page"),
        "roles": gettext("roles"),
        "Assigned": gettext("Assigned"),
        "Core roles and elected roles": gettext("Core roles and elected roles"),
        "Unassigned (held by the Circle Leads)": gettext(
            "Unassigned (held by the Circle Leads)"
        ),
        "Circle Lead": gettext("Circle Lead"),
        "Your roles": gettext("Your roles"),
        "My roles": gettext("My roles"),
        "You hold no roles.": gettext("You hold no roles."),
        "elected": gettext("elected"),
    }
    return render(
        request,
        "roles/circle_browser.html",
        {"tree": circle_tree(request.user), "labels": labels},
    )
