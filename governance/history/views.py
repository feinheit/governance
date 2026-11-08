import datetime as dt
from difflib import SequenceMatcher
from itertools import groupby

from django import forms
from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Q
from django.db.models.functions import TruncDate
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from governance.accounts.models import User
from governance.diff import similar, tokens
from governance.filters import CircleField, FilterForm
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
    "policy-domain": _("Policy moved to another domain"),
    "link-added": _("Link added"),
    "link-changed": _("Link changed"),
    "link-removed": _("Link removed"),
    "metric-added": _("Metric added"),
    "metric-changed": _("Metric changed"),
    "metric-removed": _("Metric removed"),
    "checklist-added": _("Checklist item added"),
    "checklist-changed": _("Checklist item changed"),
    "checklist-removed": _("Checklist item removed"),
}
ASSIGNMENT_KINDS = {"assigned", "unassigned", "reelected", "focus"}
# Links, metrics and checklist items: operational, shown on request
ITEM_KINDS = ("link-", "metric-", "checklist-")
# Added and removed texts of a role on a day, merged into one entry
LISTS = {
    "accountabilities": (
        _("Accountabilities changed"),
        _("Accountabilities added"),
        _("Accountabilities removed"),
    ),
    "domains": (_("Domains changed"), _("Domains added"), _("Domains removed")),
}


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


def pairs(removed, added):
    """``(old, new)`` of the texts: those replaced by a similar one as
    pairs, the most similar first, the others alone"""
    candidates = sorted(
        (
            (-SequenceMatcher(None, tokens(old), tokens(new)).ratio(), i, j)
            for i, old in enumerate(removed)
            for j, new in enumerate(added)
            if similar(old, new)
        ),
    )
    paired, used_old, used_new = {}, set(), set()
    for _ratio, i, j in candidates:
        if i not in used_old and j not in used_new:
            paired[j] = i
            used_old.add(i)
            used_new.add(j)
    return [
        *(
            (removed[paired[j]] if j in paired else "", new)
            for j, new in enumerate(added)
        ),
        *((old, "") for i, old in enumerate(removed) if i not in used_old),
    ]


def merge_lists(changes):
    """A role's accountabilities (or domains) added and removed on a day as
    one change with ``items``, like the proposal which made them"""
    merged, groups = [], {}
    for change in changes:
        field, _sep, kind = change.kind.rpartition("-")
        if field not in LISTS or kind not in {"added", "removed"}:
            merged.append(change)
            continue
        key = (change.date, change.role_id, field)
        if key not in groups:
            groups[key] = change
            change.removed, change.added = [], []
            merged.append(change)
        group = groups[key]
        (group.removed if kind == "removed" else group.added).append(
            change.old if kind == "removed" else change.new
        )
    for (_date, _role, field), change in groups.items():
        changed, added, removed = LISTS[field]
        if len(change.removed) + len(change.added) == 1:
            continue  # One text, as before
        change.kind = f"{field}-changed"
        change.label = (
            added if not change.removed else removed if not change.added else changed
        )
        change.items = pairs(change.removed, change.added)
    return merged


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
        # Links, metrics and checklist items: their text right away
        change.is_item = change.kind.startswith(ITEM_KINDS)
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
    return merge_lists(changes)


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


class RoleHistoryFilters(FilterForm):
    assignments = forms.BooleanField(label=_("With assignments"), required=False)
    operational = forms.BooleanField(
        label=_("With links, metrics and checklists"), required=False
    )


class HistoryFilters(RoleHistoryFilters):
    circle = CircleField(label=_("Circle"), empty_label=_("All circles"))
    field_order = ["circle", "assignments", "operational"]


def filtered(changes, filters):
    """Without the assignments and the operational items unless chosen"""
    if not filters.get("assignments"):
        changes = changes.exclude(kind__in=ASSIGNMENT_KINDS)
    if not filters.get("operational"):
        for prefix in ITEM_KINDS:
            changes = changes.exclude(kind__startswith=prefix)
    return changes


def role_history(request, pk):
    role = get_object_or_404(Role, pk=pk)
    filters = RoleHistoryFilters(request.GET)
    changes = filtered(role.changes.select_related("role", "policy"), filters)
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
            "filters": filters,
        },
    )


def organization_history(request):
    filters = HistoryFilters(request.GET)
    changes = filtered(Change.objects.select_related("role", "policy"), filters)
    # The days of changes and of adopted proposals (local days), e.g. one
    # with elections only, whose changes are hidden
    adopted = Proposal.objects.filter(status=Proposal.ADOPTED).annotate(
        day=TruncDate("decided_at", tzinfo=timezone.get_current_timezone())
    )
    if circle_id := filters.get("circle"):
        # The circle, its roles and those of its sub-circles
        circle = get_object_or_404(Role, pk=circle_id)
        circles = [circle, *circle.sub_circles()]
        changes = changes.filter(Q(role__in=circles) | Q(role__circle__in=circles))
        adopted = adopted.filter(circle__in=circles)
    all_days = sorted(
        set(changes.order_by().values_list("date", flat=True).distinct())
        | set(adopted.order_by().values_list("day", flat=True).distinct()),
        reverse=True,
    )
    days = Paginator(all_days, getattr(settings, "HISTORY_DAYS_PER_PAGE", 30)).get_page(
        request.GET.get("page")
    )
    dates = list(days.object_list)
    changes = changes.filter(date__in=dates)
    proposals = adopted.filter(day__in=dates).select_related("circle", "proposer")
    return render(
        request,
        "history/organization_history.html",
        {
            "timeline": timeline(changes, proposals),
            "page": days,
            "filters": filters,
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
