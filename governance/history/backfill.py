"""Audit rows for the time before the app, from GlassFrog's history

The GlassFrog import knows the structure of every day since GlassFrog's
first one (the git history of the export). ``backfill()`` turns the
differences from day to day into the audit rows a running app would have
written, so that the audit log is the whole history
(``governance.history.audit``):

- roles and policies: inserted, updated (the old row and the changed
  fields) and archived when they disappear, like the app does it;
- accountabilities and domains: inserted and deleted, a changed text is a
  deleted and an inserted row (like in the history before). Their texts
  weren't always recorded: those rows have no text. Accountabilities and
  domains which exist at the end get the IDs of their rows, the others
  negative IDs, so they never collide with real ones;
- the core roles' constitutional texts of 5.0 aren't rows, they come from
  the code (``audit.constitutional()``), also those GlassFrog didn't
  record; the texts of 4.1 before are rows.

The rows are dated at the start of their day and belong to "GlassFrog".
"""

import datetime as dt
from collections import Counter

from django.db import connection
from django.utils import timezone

from governance.history.audit import CONSTITUTION_5
from governance.roles.constitution import constitutional_texts
from governance.roles.models import Accountability, Domain


USER_NAME = "GlassFrog"
TEXTS = {"accountabilities": "roles_accountability", "domains": "roles_domain"}


def _value(value):
    """hstore stores strings, like ``hstore(NEW.*)`` does"""
    if value is None:
        return None
    if isinstance(value, bool):
        return "t" if value else "f"
    return str(value)


def _role_row(pk, entry):
    return {
        "id": pk,
        "name": entry["name"],
        "purpose": entry["purpose"],
        "circle_id": entry["circle"],
        "is_circle": entry["is_circle"],
        "core_role": entry["core_role"],
        "short_name": entry["short_name"],
        "strategy": entry["strategy"],
        "archived_on": None,
    }


def _policy_row(pk, entry):
    return {
        "id": pk,
        "role_id": entry["role"],
        "title": entry["title"],
        "body": entry["body"],
        "archived_on": None,
    }


class Backfill:
    def __init__(self):
        self.rows = []  # (table, created_at, action, row_data, changed_fields)
        self.state = {"roles_role": {}, "roles_policy": {}}
        # Per kind and role: the current rows as [id, text]
        self.texts = {kind: {} for kind in TEXTS}
        self.next_id = -1
        self.constitutional = constitutional_texts()

    def emit(self, table, at, action, row, changed=None):
        self.rows.append((table, at, action, row, changed))

    def objects(self, table, at, day, current):
        """Inserts, updates and archives roles or policies"""
        state = self.state[table]
        for pk, row in current.items():
            old = state.get(pk)
            if old is None:
                self.emit(table, at, "I", row)
            else:
                changed = {k: v for k, v in row.items() if old.get(k) != v}
                if changed:
                    self.emit(table, at, "U", old, changed)
            state[pk] = row
        for pk, old in state.items():
            if pk not in current and old["archived_on"] is None:
                state[pk] = old | {"archived_on": day.isoformat()}
                self.emit(table, at, "U", old, {"archived_on": day.isoformat()})

    def texts_of(self, at, day, roles):
        for kind, table in TEXTS.items():
            for role, entry in roles.items():
                texts = [
                    text
                    for text in entry[kind]
                    if not (entry["core_role"] and self.from_code(text, day))
                ]
                current = self.texts[kind].setdefault(role, [])
                old, new = Counter(t for _id, t in current), Counter(texts)
                for text in (old - new).elements():
                    index = next(i for i, (_id, t) in enumerate(current) if t == text)
                    pk, _text = current.pop(index)
                    self.emit(table, at, "D", self.text_row(pk, role, text))
                for text in (new - old).elements():
                    current.append([self.next_id, text])
                    self.emit(table, at, "I", self.text_row(self.next_id, role, text))
                    self.next_id -= 1

    def from_code(self, text, day):
        """A core role's text the code knows: constitutional, or from 5.0 on
        not recorded (GlassFrog only had the IDs of the constitutional ones)"""
        return text in self.constitutional or (text is None and day >= CONSTITUTION_5)

    @staticmethod
    def text_row(pk, role, text):
        return {"id": pk, "role_id": role, "text": text, "position": 0}

    def day(self, day, data):
        at = timezone.make_aware(dt.datetime.combine(day, dt.time()))
        roles = {int(pk): entry for pk, entry in data["roles"].items()}
        self.objects(
            "roles_role",
            at,
            day,
            {pk: _role_row(pk, entry) for pk, entry in roles.items()},
        )
        self.objects(
            "roles_policy",
            at,
            day,
            {
                int(pk): _policy_row(int(pk), entry)
                for pk, entry in data["policies"].items()
            },
        )
        # Archived roles keep their texts, like in the app
        self.texts_of(at, day, roles)

    def real_ids(self):
        """The IDs of the rows of the accountabilities and domains which
        exist at the end"""
        ids = {}
        for kind, model in [("accountabilities", Accountability), ("domains", Domain)]:
            real = {}
            for pk, role, text in model.objects.values_list("pk", "role_id", "text"):
                real.setdefault((role, text), []).append(pk)
            for role, current in self.texts[kind].items():
                for entry in current:
                    if pks := real.get((role, entry[1])):
                        ids[TEXTS[kind], entry[0]] = pks.pop(0)
        return ids

    def save(self):
        ids = self.real_ids()
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO audit_logged_actions
                    (table_name, user_name, created_at, action, row_data,
                    changed_fields)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        table,
                        USER_NAME,
                        at,
                        action,
                        {
                            k: _value(ids.get((table, v), v) if k == "id" else v)
                            for k, v in row.items()
                        },
                        {k: _value(v) for k, v in changed.items()} if changed else None,
                    )
                    for table, at, action, row, changed in self.rows
                ],
            )
        return len(self.rows)


def backfill(days):
    """Writes the audit rows for ``days``, ``(day, structure)`` in their
    order (see ``audit.structure_on()``), returns their number"""
    backfill = Backfill()
    for day, data in days:
        backfill.day(day, data)
    return backfill.save()
