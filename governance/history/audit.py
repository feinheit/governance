"""The structure of a past day, from the audit log

The audit log (``governance/audit/audit.sql``) records every change of
roles, accountabilities, domains and policies; the GlassFrog import fills
in the time before the app with rows from GlassFrog's history
(``governance.history.backfill``). The state of a row on a day is its last
audit row up to the end of that day: the row of an insert, the old row and
the changed fields of an update, gone after a delete. Assignments keep their
history themselves (``starts_on``, ``ends_on``).

``structure_on()`` returns the structure in the shape the history uses:
``roles`` (with their texts and holders) and ``policies``, keyed by primary
keys as strings. Texts which weren't recorded (GlassFrog only had their IDs)
are ``None``.
"""

import datetime as dt
from collections import defaultdict

from django.db import connection
from django.utils import timezone
from django.utils.translation import override

from governance.roles.constitution import CORE_ROLES
from governance.roles.models import Assignment


# Audit table → key of the structure
TABLES = {
    "roles_role": "roles",
    "roles_policy": "policies",
    "roles_accountability": "accountabilities",
    "roles_domain": "domains",
}
# The core roles' constitutional texts come from the code (constitution 5.0),
# GlassFrog switched to it on this day; the texts of 4.1 are rows
CONSTITUTION_5 = dt.date(2022, 12, 13)


def day_end(day):
    """The first moment after the day, in the local time zone"""
    return timezone.make_aware(
        dt.datetime.combine(day + dt.timedelta(days=1), dt.time())
    )


def constitutional(core_role, field, day=None):
    """Constitutional texts of a core role, in English like GlassFrog's"""
    core = CORE_ROLES.get(core_role)
    if core is None or (day and day < CONSTITUTION_5):
        return []
    with override("en"):
        return [str(text) for text in getattr(core, field)]


def rows_on(day):
    """The state of every row of the audited tables at the end of the day,
    ``{"roles": {pk: row_data}, …}``, without deleted rows"""
    rows = defaultdict(dict)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT ON (table_name, row_data -> 'id')
                table_name,
                action,
                CASE WHEN action = 'U' THEN row_data || changed_fields
                    ELSE row_data END
            FROM audit_logged_actions
            -- Without the rows of the statement level trigger
            WHERE table_name = ANY(%s) AND created_at < %s AND row_data IS NOT NULL
            ORDER BY table_name, row_data -> 'id', created_at DESC, event_id DESC
            """,
            [list(TABLES), day_end(day)],
        )
        for table, action, data in cursor.fetchall():
            if action != "D":
                rows[TABLES[table]][int(data["id"])] = data
    return rows


def assignments_on(day):
    assignments = defaultdict(list)
    for assignment in Assignment.objects.current(on=day).order_by("user_id"):
        assignments[assignment.role_id].append({
            "user": assignment.user_id,
            "elected_until": assignment.elected_until.isoformat()
            if assignment.elected_until
            else None,
        })
    return assignments


def _active(data, day):
    archived = data.get("archived_on")
    return not archived or dt.date.fromisoformat(archived) > day


def _int(value):
    return int(value) if value not in {None, ""} else None


def structure(rows, assignments, day):
    """The structure from the rows' states and the assignments of a day"""
    texts = {"accountabilities": defaultdict(list), "domains": defaultdict(list)}
    for kind, by_role in texts.items():
        for _pk, data in sorted(
            rows.get(kind, {}).items(),
            key=lambda item: (_int(item[1].get("position")) or 0, item[0]),
        ):
            by_role[_int(data["role_id"])].append(data.get("text"))
    roles = {}
    for pk, data in rows.get("roles", {}).items():
        if not _active(data, day):
            continue
        core_role = data.get("core_role") or ""
        roles[str(pk)] = {
            "name": data.get("name") or "",
            "purpose": data.get("purpose") or "",
            "circle": _int(data.get("circle_id")),
            "is_circle": data.get("is_circle") == "t",
            "core_role": core_role,
            "short_name": data.get("short_name") or "",
            "strategy": data.get("strategy") or "",
            "accountabilities": constitutional(core_role, "accountabilities", day)
            + texts["accountabilities"][pk],
            "domains": constitutional(core_role, "domains", day) + texts["domains"][pk],
            "assignments": assignments[pk],
        }
    return {
        "roles": roles,
        "policies": {
            str(pk): {
                "title": data.get("title") or "",
                "body": data.get("body") or "",
                "role": _int(data["role_id"]),
            }
            for pk, data in rows.get("policies", {}).items()
            if _active(data, day)
        },
    }


def structure_on(day):
    """The structure at the end of the given day"""
    return structure(rows_on(day), assignments_on(day), day)
