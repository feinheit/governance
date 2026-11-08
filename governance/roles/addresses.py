"""The mail addresses of groups of people, to copy into a mail: those
holding a core role in any circle (with who stands in for unfilled ones)
and the members of each circle"""

from django.shortcuts import render
from django.utils.translation import gettext as _

from governance.accounts.models import User
from governance.roles.constitution import FACILITATOR, REP, SECRETARY
from governance.roles.models import Assignment, Role
from governance.roles.permissions import (
    acting_secretaries,
    circle_leads,
    members,
    stand_ins,
)


SPECIALS = set('()<>[]:;@\\,."')


def address(user):
    """``Name <address>`` with the name as it is, quoted when it contains
    special characters; not encoded like in a header (``formataddr()``),
    mail programs take UTF-8 when pasted"""
    name = user.full_name.strip()
    if not name:
        return user.email
    if SPECIALS & set(name):
        name = '"{}"'.format(name.replace("\\", "\\\\").replace('"', '\\"'))
    return f"{name} <{user.email}>"


def group(key, label, users, *, circle=None):
    users = sorted(set(users), key=lambda user: (user.full_name or user.email).lower())
    return {
        "key": key,
        "label": label,
        "circle": circle,
        "users": users,
        # "Name <address>", what mail programs take
        "addresses": ", ".join(address(user) for user in users),
        "mailto": ",".join(u.email for u in users),
    }


def union(querysets):
    return [user for queryset in querysets for user in queryset]


def mail_addresses(request):
    circles = Role.objects.depth_first()
    with_role = User.objects.active().filter(
        assignments__in=Assignment.objects.current().filter(role__archived_on=None)
    )
    reps = User.objects.active().filter(
        assignments__in=Assignment.objects.current().of_core_role(REP, circles)
    )
    groups = [
        group("everybody", _("Everybody holding a role"), with_role),
        group(
            "circle-leads",
            _("All Circle Leads"),
            union(circle_leads(circle) for circle in circles),
        ),
        # Who stands in for unfilled ones like the app does elsewhere
        # (elections, acting_secretaries(), constitution 5.3.6)
        group(
            "facilitators",
            _("All Facilitators, or who stands in"),
            union(stand_ins(circle, [FACILITATOR, SECRETARY]) for circle in circles),
        ),
        group(
            "secretaries",
            _("All Secretaries, or who stands in"),
            union(acting_secretaries(circle) for circle in circles),
        ),
        group("circle-reps", _("All Circle Reps"), reps),
    ]
    circle_groups = [
        group(f"circle-{circle.pk}", circle.name, members(circle), circle=circle)
        for circle in circles
    ]
    return render(
        request,
        "roles/mail_addresses.html",
        {"groups": groups, "circle_groups": circle_groups},
    )
