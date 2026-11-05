"""The changes from day to day, from the audit log (``history.audit``)

``Change`` is a cache of them for the history pages: what changed on which
day, also without a proposal (in GlassFrog outside governance) and who held
which role when.
"""

import datetime as dt
from collections import defaultdict

from django.db import connection, transaction
from django.utils import timezone

from governance.history.audit import TABLES, day_end, rows_on, structure
from governance.history.changes import diff_policies, diff_roles
from governance.history.models import Change
from governance.roles.models import Assignment, Policy, Role


def _audit_rows(since):
    """The audit rows' states in their order, from ``since`` on"""
    after = "AND created_at >= %s" if since else ""
    params = [list(TABLES)] + ([day_end(since - dt.timedelta(days=1))] if since else [])
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
                table_name,
                action,
                CASE WHEN action = 'U' THEN row_data || changed_fields
                    ELSE row_data END,
                created_at
            FROM audit_logged_actions
            WHERE table_name = ANY(%s) AND row_data IS NOT NULL {after}
            ORDER BY created_at, event_id
            """,
            params,
        )
        yield from cursor


class Holders:
    """Who held which role on a day, from all assignments in memory"""

    def __init__(self):
        self.assignments = list(
            Assignment.objects.order_by("user_id").values_list(
                "role_id", "user_id", "starts_on", "ends_on", "elected_until"
            )
        )

    def days(self):
        return {
            day
            for _role, _user, starts_on, ends_on, _elected in self.assignments
            for day in (starts_on, ends_on)
            if day
        }

    def on(self, day):
        holders = defaultdict(list)
        for role, user, starts_on, ends_on, elected in self.assignments:
            if (not starts_on or starts_on <= day) and (not ends_on or ends_on > day):
                holders[role].append({
                    "user": user,
                    "elected_until": elected.isoformat() if elected else None,
                })
        return holders


@transaction.atomic
def update_changes(*, since=None):
    """Recomputes the changes (from ``since`` on) by replaying the audit log
    and comparing the structure from day to day"""
    changes = Change.objects.all()
    if since:
        changes = changes.filter(date__gte=since)
    changes.delete()

    holders = Holders()
    by_day = defaultdict(list)
    for table, action, data, created_at in _audit_rows(since):
        by_day[timezone.localdate(created_at)].append((TABLES[table], action, data))
    days = sorted(
        set(by_day) | {day for day in holders.days() if not since or day >= since}
    )
    if since:
        previous_day = since - dt.timedelta(days=1)
        rows = rows_on(previous_day)
        previous = structure(rows, holders.on(previous_day), previous_day)
    else:
        rows, previous = defaultdict(dict), None

    roles = set(Role.objects.values_list("pk", flat=True))
    policies = set(Policy.objects.values_list("pk", flat=True))
    new = []
    for day in days:
        for kind, action, data in by_day.get(day, []):
            if action == "D":
                rows[kind].pop(int(data["id"]), None)
            else:
                rows[kind][int(data["id"])] = data
        current = structure(rows, holders.on(day), day)
        if previous is not None:
            for role, kind, old, value in diff_roles(previous, current):
                if role in roles:
                    new.append(
                        Change(date=day, role_id=role, kind=kind, old=old, new=value)
                    )
            for policy, role, kind, old, value in diff_policies(previous, current):
                if policy in policies:
                    new.append(
                        Change(
                            date=day,
                            policy_id=policy,
                            role_id=role if role in roles else None,
                            kind=f"policy-{kind}",
                            old=old,
                            new=value,
                        )
                    )
        previous = current
    Change.objects.bulk_create(new, batch_size=1000)
    return len(new)
