"""Snapshots of the governance in the database, see ``Snapshot.data``

The GlassFrog import writes the snapshots of the GlassFrog period, the daily
task writes them afterwards (``take_snapshot()``), only on days with
changes.
"""

from collections import defaultdict

from django.db import transaction
from django.utils import timezone
from django.utils.translation import override

from governance.history.models import Snapshot
from governance.history.update import update_changes
from governance.roles.constitution import CORE_ROLES
from governance.roles.models import Assignment, Policy, Role


def constitutional(role, field):
    """Constitutional texts of core roles, in English like GlassFrog's"""
    core = CORE_ROLES.get(role.core_role)
    if core is None:
        return []
    with override("en"):
        return [str(text) for text in getattr(core, field)]


def build_snapshot(day):
    """The structure of the given day from the database"""
    assignments = defaultdict(list)
    for assignment in Assignment.objects.current(on=day).order_by("user_id"):
        assignments[assignment.role_id].append({
            "user": assignment.user_id,
            "elected_until": assignment.elected_until.isoformat()
            if assignment.elected_until
            else None,
        })
    roles = Role.objects.active().prefetch_related("accountabilities", "domains")
    return {
        "roles": {
            str(role.pk): {
                "name": role.name,
                "purpose": role.purpose,
                "circle": role.circle_id,
                "is_circle": role.is_circle,
                "core_role": role.core_role,
                "short_name": role.short_name,
                "strategy": role.strategy,
                "accountabilities": constitutional(role, "accountabilities")
                + [a.text for a in role.accountabilities.all()],
                "domains": constitutional(role, "domains")
                + [d.text for d in role.domains.all()],
                "assignments": assignments[role.pk],
            }
            for role in roles
        },
        "policies": {
            str(policy.pk): {
                "title": policy.title,
                "body": policy.body,
                "role": policy.role_id,
            }
            for policy in Policy.objects.active()
        },
    }


def canonical(data):
    """``data`` without the order of texts and holders, for comparing"""
    return {
        "roles": {
            pk: entry
            | {
                "accountabilities": sorted(entry["accountabilities"], key=str),
                "domains": sorted(entry["domains"], key=str),
                "assignments": sorted(
                    entry["assignments"], key=lambda a: (a["user"], str(a))
                ),
            }
            for pk, entry in data.get("roles", {}).items()
        },
        "policies": data.get("policies", {}),
    }


@transaction.atomic
def take_snapshot(day=None):
    """Stores the snapshot of the day if something changed, returns it"""
    day = day or timezone.localdate()
    data = build_snapshot(day)
    previous = Snapshot.objects.filter(date__lt=day).order_by("date").last()
    if previous is not None and canonical(previous.data) == canonical(data):
        if Snapshot.objects.filter(date=day).delete()[0]:
            update_changes(since=day)
        return None
    snapshot, _created = Snapshot.objects.update_or_create(
        date=day, defaults={"data": data}
    )
    update_changes(since=day)
    return snapshot
