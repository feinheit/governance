import datetime as dt
from itertools import groupby

from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from governance.accounts.models import User
from governance.history.audit import structure_on
from governance.history.models import Change
from governance.proposals.models import Proposal
from governance.roles.constitution import LEAD, REP
from governance.roles.models import Role


LABELS = {
    "added": _("Role added"),
    "removed": _("Role removed"),
    "name": _("Renamed"),
    "purpose": _("Purpose changed"),
    "strategy": _("Strategy changed"),
    "moved": _("Moved to another circle"),
    "circle": _("Turned into a circle"),
    "role": _("Turned back into a role"),
    "accountabilities-added": _("Accountability added"),
    "accountabilities-removed": _("Accountability removed"),
    "accountabilities-unrecorded": _("Accountabilities changed (texts not recorded)"),
    "domains-added": _("Domain added"),
    "domains-removed": _("Domain removed"),
    "domains-unrecorded": _("Domains changed (texts not recorded)"),
    "assigned": _("Assigned"),
    "unassigned": _("No longer assigned"),
    "reelected": _("Re-elected"),
    "focus": _("Focus changed"),
    "policy-added": _("Policy added"),
    "policy-removed": _("Policy removed"),
    "policy-title": _("Policy renamed"),
    "policy-body": _("Policy text changed"),
    "policy-moved": _("Policy moved"),
}
ASSIGNMENT_KINDS = {"assigned", "unassigned", "reelected", "focus"}


def user_of(change):
    """``old`` or ``new`` of assignments; re-elections have the term in
    ``new``, changes of the focus the user and the focus in both"""
    if change.kind == "reelected":
        return change.old
    if change.kind == "focus":
        return change.new["user"]
    return change.new or change.old


def without_following(changes):
    """Without the assignments of a circle's role which follow those of its
    Circle Leads and Reps on the same day (``sync_circle_holders()``)"""
    core = {
        (change.date, change.kind, user_of(change), change.role.circle_id)
        for change in changes
        if change.kind in {"assigned", "unassigned"}
        and change.role
        and change.role.core_role in {LEAD, REP}
    }
    return [
        change
        for change in changes
        if not (
            change.role
            and change.role.is_circle
            and (change.date, change.kind, user_of(change), change.role_id) in core
        )
    ]


def present(changes):
    """Readable labels, users and roles for the template"""
    changes = without_following(list(changes))
    user_ids, role_ids = set(), set()
    for change in changes:
        if change.kind in ASSIGNMENT_KINDS:
            user_ids.add(user_of(change))
        elif change.kind in {"moved", "policy-moved"}:
            role_ids.update(value for value in [change.old, change.new] if value)
    users = User.objects.in_bulk(user_ids)
    roles = Role.objects.in_bulk(role_ids)
    for change in changes:
        change.label = LABELS.get(change.kind, change.kind)
        change.old_text = change.old if isinstance(change.old, str) else ""
        change.new_text = change.new if isinstance(change.new, str) else ""
        change.user = (
            users.get(user_of(change)) if change.kind in ASSIGNMENT_KINDS else None
        )
        if change.kind == "focus":
            change.old_text, change.new_text = (
                change.old["focus"],
                change.new["focus"],
            )
        if change.kind == "reelected":
            # ``new`` is the end of the term, not a text
            change.term, change.new_text = dt.date.fromisoformat(change.new), ""
        if change.kind in {"moved", "policy-moved"}:
            change.old_role, change.new_role = (
                roles.get(change.old),
                roles.get(change.new),
            )
    return changes


def timeline(changes, proposals):
    """Changes and proposals grouped by day, newest first"""
    entries = [(change.date, "change", change) for change in present(changes)] + [
        # The local day like the changes', not UTC's
        (timezone.localdate(proposal.decided_at), "proposal", proposal)
        for proposal in proposals
    ]
    entries.sort(key=lambda entry: (entry[0], entry[1] == "proposal"), reverse=True)
    return [
        (day, [(kind, obj) for _day, kind, obj in group])
        for day, group in groupby(entries, key=lambda entry: entry[0])
    ]


def role_history(request, pk):
    role = get_object_or_404(Role, pk=pk)
    changes = role.changes.select_related("role", "policy")
    if not request.GET.get("assignments"):
        changes = changes.exclude(kind__in=ASSIGNMENT_KINDS)
    proposals = role.changed_by_proposals.filter(
        status=Proposal.ADOPTED
    ).select_related("proposer")
    return render(
        request,
        "history/role_history.html",
        {
            "role": role,
            "ancestors": role.ancestors(),
            "timeline": timeline(changes, proposals),
            "assignments": bool(request.GET.get("assignments")),
        },
    )


def organization_history(request):
    changes = Change.objects.select_related("role", "policy")
    if not request.GET.get("assignments"):
        changes = changes.exclude(kind__in=ASSIGNMENT_KINDS)
    days = Paginator(
        changes.values_list("date", flat=True).distinct().order_by("-date"), 30
    ).get_page(request.GET.get("page"))
    dates = list(days.object_list)
    changes = changes.filter(date__in=dates)
    proposals = (
        Proposal.objects.filter(
            status=Proposal.ADOPTED,
            decided_at__date__gte=min(dates) - dt.timedelta(days=1) if dates else None,
            decided_at__date__lte=max(dates) if dates else None,
        ).select_related("circle", "proposer")
        if dates
        else []
    )
    return render(
        request,
        "history/organization_history.html",
        {
            "timeline": timeline(changes, proposals),
            "page": days,
            "assignments": bool(request.GET.get("assignments")),
        },
    )


def role_as_of(request, pk):
    role = get_object_or_404(Role, pk=pk)
    try:
        day = dt.date.fromisoformat(request.GET.get("date", ""))
    except ValueError:
        day = dt.date.today()
    data = structure_on(day)
    if not data["roles"]:
        raise Http404("Before the history")
    entries = data["roles"]
    entry = entries.get(str(role.pk))
    users = User.objects.in_bulk({
        a["user"] for e in entries.values() for a in e["assignments"]
    })

    def holders(data):
        return [
            (users.get(a["user"]), a.get("elected_until")) for a in data["assignments"]
        ]

    children = []
    if entry:
        for child_pk, child in entries.items():
            if child["circle"] == role.pk:
                children.append(
                    {"pk": int(child_pk), "holders": holders(child)} | child
                )
        children.sort(
            key=lambda child: (
                not child["core_role"],
                not child["is_circle"],
                child["name"],
            )
        )
        entry = entry | {"holders": holders(entry)}
    policies = [
        {"pk": int(policy_pk)} | policy
        for policy_pk, policy in data["policies"].items()
        if policy["role"] == role.pk
    ]
    return render(
        request,
        "history/role_as_of.html",
        {
            "role": role,
            "entry": entry,
            "children": children,
            "policies": sorted(policies, key=lambda policy: policy["title"]),
            "day": day,
            "unrecorded": sum(
                1 for text in (entry or {}).get("accountabilities", []) if text is None
            ),
        },
    )
