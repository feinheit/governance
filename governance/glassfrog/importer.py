"""Importing the GlassFrog export, see section 8 of ``SPEC.md``

The import is idempotent (by GlassFrog IDs and dates) and runs while
GlassFrog is the source of truth: it replaces the assignments of imported
roles, and the accountabilities, domains and policies of the current roles.
"""

import datetime as dt
import re
import time
from collections import defaultdict
from contextlib import contextmanager

from django.conf import settings
from django.db import connection, transaction
from django.utils.dateparse import parse_datetime

from governance.accounts.middleware import set_user_name
from governance.accounts.models import User
from governance.glassfrog.export import Export, without_empty
from governance.glassfrog.normalize import normalize
from governance.history.audit import TABLES as AUDIT_TABLES, structure_from_database
from governance.history.backfill import USER_NAME as BACKFILL_USER, Backfill
from governance.history.update import update_changes
from governance.meetings.models import AgendaItem, Meeting
from governance.proposals.models import Proposal
from governance.roles.constitution import constitutional_texts
from governance.roles.mentions import MentionResolver
from governance.roles.models import (
    ASYNC_ACCEPTANCE_DAYS,
    FREQUENCY_CHOICES,
    Accountability,
    Assignment,
    ChecklistItem,
    Domain,
    Metric,
    Policy,
    Role,
)


PROPOSAL_STATUS = {
    "accepted": Proposal.ADOPTED,
    "draft": Proposal.DRAFT,
    "draft_with_conflicts": Proposal.DRAFT,
    "proposed_outside_meeting": Proposal.PUBLISHED,
    "escalated": Proposal.IN_MEETING,
}
# Escalated proposals nobody brought to a governance meeting for this long
# go back to their proposers as drafts (the nightly import also moves the
# ones imported before)
ESCALATED_STALE_AFTER = dt.timedelta(days=60)

PATH_OBJECTS = re.compile(r"(roles|circles|policies|accountabilities|domains)/(\d+)")


def to_app_ids(instructions, names, ids):
    """Instructions and names of a proposal with the app's IDs instead of
    GlassFrog's, for proposals the app will adopt

    ``ids`` maps ``(kind, glassfrog_id)`` to the app's ID (circles to their
    role's). Objects the proposal adds get keys like ``n1`` like in the app,
    unknown ones stay, the app reports them as missing."""
    added = {}
    for instruction in instructions:
        if instruction["op"] == "add" and (
            match := re.search(
                # New accountabilities and domains also with /description
                r"/(roles|policies|accountabilities|domains)/(\d+)(?:/description)?$",
                instruction["path"],
            )
        ):
            key = (match[1], int(match[2]))
            if key not in ids and key not in added:
                added[key] = f"n{len(added) + 1}"

    def translate(text):
        def object_id(match):
            key = (match[1], int(match[2]))
            new = ids.get(key) or added.get(key) or match[2]
            return f"{match[1]}/{new}"

        return PATH_OBJECTS.sub(object_id, text)

    translated = []
    for instruction in instructions:
        new = {**instruction, "path": translate(instruction["path"])}
        if "from" in new:
            new["from"] = translate(new["from"])
        translated.append(new)
    return translated, {translate(key): name for key, name in names.items()}


def parse(value):
    return parse_datetime(value) if value else None


def is_redacted(person):
    """GlassFrog replaces people who left by "Removed" and a redacted email"""
    return person["name"] == "Removed" or person["email"].startswith("[redacted]")


class History:
    """What the import learns from walking all snapshots"""

    def __init__(self):
        self.days = []
        self.roles = {}  # GlassFrog role ID → (last day seen, entry)
        self.policies = {}  # GlassFrog policy ID → (last day seen, entry)
        self.domains = {}  # GlassFrog domain ID → text
        self.people = {}  # GlassFrog person ID → {"name", "email"}
        self.circle_roles = {}  # GlassFrog circle ID → role ID
        self.names = defaultdict(list)  # "roles/123" → [(day, name), …]
        self.intervals = []  # (role ID, person ID, starts_on, ends_on)
        self._open = {}

    def add(self, day, snapshot):
        self.days.append(day)
        for role_id, entry in snapshot["roles"].items():
            self.roles[role_id] = (day, entry)
            self._name(f"roles/{role_id}", day, entry["name"])
            if entry["is_circle"]:
                self._name(f"circles/{entry['circle_id']}", day, entry["name"])
        for policy_id, entry in snapshot["policies"].items():
            self.policies[policy_id] = (day, entry)
            self._name(f"policies/{policy_id}", day, entry["title"])
        for domain_id, text in snapshot["domains"].items():
            self.domains[domain_id] = text
            self._name(f"domains/{domain_id}", day, text)
        for role_id, short_name in snapshot["short_names"].items():
            self._name(f"roles/{role_id}", day, short_name)
        self.people |= {
            person_id: person
            for person_id, person in snapshot["people"].items()
            if not is_redacted(person)
        }
        self.circle_roles |= snapshot["circle_roles"]

        present = {
            (role_id, person_id)
            for role_id, entry in snapshot["roles"].items()
            for person_id in entry["people"]
        }
        for key in present - self._open.keys():
            self._open[key] = day
        for key in self._open.keys() - present:
            self.intervals.append((*key, self._open.pop(key), day))

    def finish(self):
        self.intervals.extend((*key, start, None) for key, start in self._open.items())
        self._open = {}

    def _name(self, key, day, name):
        names = self.names[key]
        if not names or names[-1][1] != name:
            names.append((day, name))

    def name(self, key, day):
        """The name of an object on the given day, or the closest one known"""
        names = self.names.get(key)
        if not names:
            return None
        before = [name for since, name in names if since <= day]
        return before[-1] if before else names[0][1]

    def archived_on(self, last_seen):
        """The first day of a snapshot without the object, None if current"""
        later = [day for day in self.days if day > last_seen]
        return later[0] if later else None


class Importer:
    """Imports an ``Export`` (with history) or an ``ApiExport`` (today only)

    An export without history is imported incrementally: the history in the
    database stays, roles and policies GlassFrog doesn't return anymore are
    archived today, assignments start and end today, and proposals keep the
    names they had.
    """

    def __init__(self, export, *, log=print):
        self.export = export if hasattr(export, "snapshots") else Export(export)
        self.incremental = self.export.incremental
        self.log = log
        self.history = History()
        self.users = {}  # GlassFrog person ID → User
        self.roles = {}  # GlassFrog role ID → Role
        self.policies = {}  # GlassFrog policy ID → Policy
        self.accountability_texts = {}  # GlassFrog ID → text
        self.stats = defaultdict(int)

    @contextmanager
    def step(self, label):
        """Logs the step and how long it took, the import runs for minutes"""
        self.log(f"{label}…")
        start = time.monotonic()
        try:
            yield
        finally:  # Also when it fails, the traceback follows
            self.log(f"{label}: {time.monotonic() - start:.1f}s")

    def run(self):
        start = time.monotonic()
        # The audit log names the import; its own rows of a full import are
        # replaced by the backfilled history (import_history())
        set_user_name("GlassFrog import")
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT coalesce(max(event_id), 0) FROM audit_logged_actions"
            )
            self.first_event = cursor.fetchone()[0]
        with self.step("Reading the snapshots"):
            for day, data in self.export.snapshots():
                self.history.add(day, normalize(data))
            self.history.finish()
        self.log(f"{len(self.history.days)} snapshots, {len(self.history.roles)} roles")

        self.files = {}
        for name in [
            "roles",
            "assignments",
            "policies",
            "proposals",
            "tensions",
            "governance_meetings",
            "tactical_meetings",
            "metrics",
            "checklist_items",
        ]:
            with self.step(f"Loading {name}"):
                self.files[name] = self.export.load(f"{name}.json") or {}

        if self.incremental:
            # Earlier people, roles and policies: GlassFrog returns people who
            # left redacted, proposals and meetings refer to all of them
            self.users = {
                u.glassfrog_id: u for u in User.objects.exclude(glassfrog_id=None)
            }
            self.roles = {
                r.glassfrog_id: r for r in Role.objects.exclude(glassfrog_id=None)
            }
            self.policies = {
                p.glassfrog_id: p for p in Policy.objects.exclude(glassfrog_id=None)
            }

        with transaction.atomic():
            for label, method in [
                ("Users", self.import_users),
                ("Roles", self.import_roles),
                (
                    "Accountabilities and domains",
                    self.import_accountabilities_and_domains,
                ),
                ("Policies", self.import_policies),
                ("Assignments", self.import_assignments),
                ("Metrics", lambda: self.import_role_items(Metric, "metrics")),
                (
                    "Checklist items",
                    lambda: self.import_role_items(ChecklistItem, "checklist_items"),
                ),
                ("Proposals", self.import_proposals),
                ("Tensions", self.import_tensions),
                ("Meetings", self.import_meetings),
                ("Mentions", self.convert_mentions),
            ]:
                with self.step(label):
                    method()
        if not self.incremental:
            # The nightly import's changes are audit rows by themselves
            with self.step("History"), transaction.atomic():
                self.import_history()
        with self.step("Changes"):
            self.stats["changes"] = update_changes(
                since=self.history.days[0]
                if self.incremental and self.history.days
                else None
            )

        for key, value in sorted(self.stats.items()):
            self.log(f"{key}: {value}")
        self.log(f"Done in {time.monotonic() - start:.0f}s")
        return self.stats

    # Users ###################################################################

    def import_users(self):
        people = dict(self.history.people)
        current = set()
        for name in [
            "roles",
            "proposals",
            "governance_meetings",
            "tactical_meetings",
            "assignments",
            "tensions",
        ]:
            for data in without_empty(self.files[name].get("linked", {}).get("people")):
                person = {
                    "name": data.get("name") or "",
                    "email": data.get("email") or "",
                }
                if is_redacted(person):
                    # The snapshots may still know them, or nobody does
                    self.stats["people only known redacted"] += (
                        data["id"] not in people and data["id"] not in self.users
                    )
                    continue
                people[data["id"]] = person
                if name == "roles":
                    current.add(data["id"])
        if not current:  # No roles.json, the newest snapshot knows who is there
            last = self.history.days[-1] if self.history.days else None
            current = {
                person_id
                for (day, entry) in self.history.roles.values()
                if day == last
                for person_id in entry["people"]
            }

        for person_id, person in people.items():
            email = person["email"].strip().lower()
            if not email:
                continue
            user = User.objects.filter(email=email).first()
            if user is None:
                user = User.objects.create_user(
                    email, full_name=person["name"], is_active=person_id in current
                )
                self.stats["users created"] += 1
                if not user.is_active:
                    self.log(f"Inactive user created: {user}")
            if not user.full_name and person["name"]:
                user.full_name = person["name"]
            if (
                user.glassfrog_id is None
                and not User.objects.filter(glassfrog_id=person_id).exists()
            ):
                user.glassfrog_id = person_id
            user.save(update_fields=["full_name", "glassfrog_id"])
            self.users[person_id] = user

        # The admins of the installation administer it from the start
        for _name, email in settings.ADMINS:
            user, created = User.objects.get_or_create(email=email.lower())
            if created or not (user.is_admin and user.is_active):
                user.is_admin = user.is_active = True
                user.save(update_fields=["is_admin", "is_active"])
                self.log(f"Admin: {user}")

    # Structure ###############################################################

    def import_roles(self):
        history = self.history
        current = {
            role["id"]: role for role in without_empty(self.files["roles"].get("roles"))
        }
        for role_id, (last_seen, entry) in history.roles.items():
            role = Role.objects.filter(glassfrog_id=role_id).first() or Role(
                glassfrog_id=role_id
            )
            # Earlier names and short names, kept across incremental imports
            names = {name for _day, name in history.names.get(f"roles/{role_id}", [])}
            if self.incremental:
                names |= {role.name, role.short_name, *role.other_names}
            role.name = entry["name"]
            role.purpose = (current.get(role_id) or {}).get("purpose") or entry[
                "purpose"
            ]
            role.core_role = "" if entry["is_circle"] else entry["core_role"]
            role.is_circle = entry["is_circle"]
            role.position = {"lead": 0, "facilitator": 1, "secretary": 2, "rep": 3}.get(
                role.core_role, 10
            )
            role.archived_on = history.archived_on(last_seen)
            if entry["is_circle"]:
                role.glassfrog_circle_id = entry["circle_id"]
                role.short_name = (
                    entry["short_name"] if entry["short_name"] != entry["name"] else ""
                )
                role.strategy = entry["strategy"]
            else:
                role.glassfrog_circle_id = None
            role.other_names = sorted(names - {role.name, ""})
            role.circle = None  # Set below, the circle may not exist yet
            role.save()
            self.roles[role_id] = role
            self.stats["roles"] += 1

        for role_id, (_last_seen, entry) in history.roles.items():
            if entry["circle"] is not None:
                role = self.roles[role_id]
                role.circle = self.roles.get(entry["circle"])
                role.save(update_fields=["circle"])
            elif entry["is_circle"]:
                # GlassFrog has no setting for it, only a policy: the
                # default at the top, sub-circles inherit it; kept once set
                role = self.roles[role_id]
                if role.async_acceptance_days is None:
                    role.async_acceptance_days = ASYNC_ACCEPTANCE_DAYS
                    role.save(update_fields=["async_acceptance_days"])

        if self.incremental and history.days:
            # Roles GlassFrog doesn't return anymore
            for role_id, role in self.roles.items():
                if role_id not in history.roles and role.archived_on is None:
                    role.archived_on = history.days[-1]
                    role.save(update_fields=["archived_on"])
                    self.stats["roles archived"] += 1

    def import_accountabilities_and_domains(self):
        roles = self.files["roles"]
        linked = roles.get("linked", {})
        accountabilities = {
            a["id"]: a.get("description") or ""
            for a in without_empty(linked.get("accountabilities"))
        }
        domains = {
            d["id"]: d.get("description") or ""
            for d in without_empty(linked.get("domains"))
        }
        self.domain_texts = domains
        self.accountability_texts |= accountabilities
        # Accountability texts set or replaced by proposals, the newest wins
        for proposal in sorted(
            self.files["proposals"].get("proposals", []),
            key=lambda proposal: proposal.get("accepted_at") or "",
        ):
            for instruction in proposal.get("instructions", []):
                match = re.fullmatch(
                    r"/roles/\d+/accountabilities/(\d+)/description",
                    instruction["path"],
                )
                if match and instruction.get("value"):
                    self.accountability_texts.setdefault(
                        int(match[1]), instruction["value"]
                    )
        self.accountability_texts |= accountabilities

        constitutional = constitutional_texts()
        for data in without_empty(roles.get("roles")):
            role = self.roles.get(data["id"])
            if role is None or role.archived_on:
                continue
            links = data["links"]
            for model, ids, texts in [
                (Accountability, links.get("accountabilities") or [], accountabilities),
                (Domain, links.get("domains") or [], domains),
            ]:
                keep = []
                for position, glassfrog_id in enumerate(ids):
                    text = texts.get(glassfrog_id, "")
                    if role.core_role and text in constitutional:
                        continue
                    obj, _created = model.objects.update_or_create(
                        glassfrog_id=glassfrog_id,
                        defaults={"role": role, "text": text, "position": position},
                    )
                    keep.append(obj.pk)
                    self.stats[model._meta.db_table.removeprefix("roles_")] += 1
                model.objects.filter(role=role).exclude(pk__in=keep).delete()

    def import_policies(self):
        current = {
            policy["id"]: policy
            for policy in without_empty(self.files["policies"].get("policies"))
        }
        circle_roles = self.history.circle_roles
        domains = {
            domain.glassfrog_id: domain
            for domain in Domain.objects.exclude(glassfrog_id=None)
        }
        ids = set(self.history.policies) | set(current)
        for policy_id in ids:
            last_seen, entry = self.history.policies.get(policy_id, (None, None))
            data = current.get(policy_id)
            if data is not None:
                links = data.get("links", {})
                owner = links.get("role") or circle_roles.get(links.get("circle"))
                entry = {
                    "title": data.get("title") or "",
                    "body": data.get("body") or "",
                    "role": owner,
                    "domain": links.get("domain"),
                }
                archived_on = None
            else:
                archived_on = (
                    self.history.archived_on(last_seen)
                    if not current
                    else self.history.archived_on(last_seen) or self.history.days[-1]
                )
            role = self.roles.get(entry["role"])
            if role is None:
                self.stats["policies without a known role"] += 1
                continue
            policy, _created = Policy.objects.update_or_create(
                glassfrog_id=policy_id,
                defaults={
                    "role": role,
                    "title": entry["title"],
                    "body": entry["body"],
                    "domain": domains.get(entry["domain"]),
                    "archived_on": archived_on,
                },
            )
            self.policies[policy_id] = policy
            self.stats["policies"] += 1

        if self.incremental and self.history.days:
            # Policies GlassFrog doesn't return anymore
            for policy_id, policy in self.policies.items():
                if policy_id not in ids and policy.archived_on is None:
                    policy.archived_on = self.history.days[-1]
                    policy.save(update_fields=["archived_on"])
                    self.stats["policies archived"] += 1

    def import_assignments(self):
        current = defaultdict(list)
        for assignment in self.files["assignments"].get("assignments", []):
            links = assignment["links"]
            current[(links["role"], links["person"])].append(assignment)
        if self.incremental:
            self.update_assignments(current)
            return

        Assignment.objects.filter(role__glassfrog_id__isnull=False).delete()

        first_day = self.history.days[0] if self.history.days else None
        for role_id, person_id, starts_on, ends_on in self.history.intervals:
            role = self.roles.get(role_id)
            user = self.users.get(person_id)
            if role is None or user is None:
                continue
            since = None if starts_on == first_day else starts_on
            rows = current.pop((role_id, person_id), None) if ends_on is None else None
            for row in rows or [None]:
                Assignment.objects.create(
                    role=role,
                    user=user,
                    starts_on=since,
                    ends_on=ends_on,
                    focus=(row or {}).get("focus") or "",
                    elected_until=(row or {}).get("election"),
                    glassfrog_id=(row or {}).get("id"),
                )
                self.stats["assignments"] += 1

        # Current assignments the snapshots don't list (e.g. of the roles of
        # some sub-circles), since an unknown date
        for (role_id, person_id), rows in current.items():
            role = self.roles.get(role_id)
            user = self.users.get(person_id)
            if role is None or user is None:
                continue
            for row in rows:
                Assignment.objects.create(
                    role=role,
                    user=user,
                    focus=row.get("focus") or "",
                    elected_until=row.get("election"),
                    glassfrog_id=row["id"],
                )
                self.stats["assignments"] += 1

    def update_assignments(self, current):
        """Assignments start and end today, the earlier ones stay"""
        day = self.history.days[-1]
        # Who holds which role today: the snapshot and assignments.json
        wanted = {
            (role_id, person_id): []
            for role_id, (_day, entry) in self.history.roles.items()
            for person_id in entry["people"]
        } | {key: list(rows) for key, rows in current.items()}
        # Not of archived roles: GlassFrog still lists the holders of the core
        # roles of circles which are roles here (normalize())
        wanted = {
            key: rows
            for key, rows in wanted.items()
            if (role := self.roles.get(key[0])) and role.archived_on is None
        }
        persons = {user.pk: person_id for person_id, user in self.users.items()}

        for assignment in Assignment.objects.filter(
            role__glassfrog_id__isnull=False, ends_on=None
        ).select_related("role"):
            key = (assignment.role.glassfrog_id, persons.get(assignment.user_id))
            if key not in wanted:
                assignment.ends_on = day
                assignment.save(update_fields=["ends_on"])
                self.stats["assignments ended"] += 1
                continue
            rows = wanted[key]
            row = next(
                (r for r in rows if r["id"] == assignment.glassfrog_id), None
            ) or (rows[0] if rows else None)
            if row:
                rows.remove(row)
                assignment.focus = row.get("focus") or ""
                assignment.elected_until = row.get("election")
                assignment.glassfrog_id = row["id"]
                assignment.save(
                    update_fields=["focus", "elected_until", "glassfrog_id"]
                )
            if not rows:
                del wanted[key]

        for (role_id, person_id), rows in wanted.items():
            role = self.roles.get(role_id)
            user = self.users.get(person_id)
            if role is None or user is None:
                continue
            for row in rows or [{}]:
                Assignment.objects.create(
                    role=role,
                    user=user,
                    starts_on=day,
                    focus=row.get("focus") or "",
                    elected_until=row.get("election"),
                    glassfrog_id=row.get("id"),
                )
                self.stats["assignments started"] += 1

    def import_role_items(self, model, name):
        """Metrics and checklist items of a role, of a circle, or of the whole
        organization (neither circle nor role: the anchor circle)"""
        circle_roles = self.history.circle_roles
        anchor = Role.objects.active().circles().filter(circle=None).first()
        for item in self.files[name].get(name, []):
            links = item.get("links", {})
            if not links.get("role") and not links.get("circle"):
                role = anchor
            else:
                role = self.roles.get(links.get("role")) or self.roles.get(
                    circle_roles.get(links.get("circle"))
                )
            if role is None or role.archived_on:
                self.stats[f"{name} of roles which are gone"] += 1
                continue
            model.objects.update_or_create(
                glassfrog_id=item["id"],
                defaults={
                    "role": role,
                    "description": item.get("description") or "",
                    # GlassFrog's "Weekly" etc.
                    "frequency": (item.get("frequency") or "").lower()
                    if (item.get("frequency") or "").lower() in dict(FREQUENCY_CHOICES)
                    else "",
                    "link": item.get("link") or "",
                },
            )
            self.stats[name] += 1

    # Governance history ######################################################

    def circle(self, glassfrog_circle_id, linked_circles=()):
        if self.incremental and glassfrog_circle_id:
            role = Role.objects.filter(glassfrog_circle_id=glassfrog_circle_id).first()
            if role:
                return role
        role_id = self.history.circle_roles.get(glassfrog_circle_id)
        if role_id is None:
            for circle in linked_circles:
                if circle["id"] == glassfrog_circle_id:
                    role_id = circle["links"].get("supported_role")
        return self.roles.get(role_id)

    def names(self, instructions, day):
        names = {}
        for instruction in instructions:
            for match in PATH_OBJECTS.finditer(
                f"{instruction['path']} {instruction.get('from', '')}"
            ):
                key = f"{match[1]}/{match[2]}"
                if key in names:
                    continue
                if match[1] == "accountabilities":
                    name = self.accountability_texts.get(int(match[2]))
                else:
                    name = self.history.name(key, day)
                if name is not None:
                    names[key] = name
            # The proposal's own additions, e.g. roles created before the
            # first snapshot
            path = instruction["path"]
            value = instruction.get("value") or instruction.get("original_value")
            if (
                isinstance(value, str)
                and value
                and (
                    (
                        match := re.fullmatch(
                            r"/(roles|policies)/(\d+)/(name|title)", path
                        )
                    )
                    or (
                        match := re.fullmatch(
                            r"/roles/\d+/(accountabilities|domains)/(\d+)(/description)?",
                            path,
                        )
                    )
                )
            ):
                names.setdefault(f"{match[1]}/{match[2]}", value)
        return names

    def import_proposals(self):
        data = self.files["proposals"]
        linked = data.get("linked", {})
        tensions = {
            tension["id"]: tension for tension in without_empty(linked.get("tensions"))
        }
        circles = without_empty(linked.get("circles"))
        # Today's snapshot only knows today's names, keep the earlier ones
        earlier = (
            dict(
                Proposal.objects.exclude(glassfrog_id=None).values_list(
                    "glassfrog_id", "names"
                )
            )
            if self.incremental
            else {}
        )
        on_agenda = set(
            Proposal.objects
            .exclude(glassfrog_id=None)
            .filter(status=Proposal.IN_MEETING, meeting__isnull=False)
            .values_list("glassfrog_id", flat=True)
        )
        last_day = self.history.days[-1] if self.history.days else None
        # GlassFrog's IDs of the current objects, for open proposals
        ids = {}
        for kind, model, field in [
            ("roles", Role, "glassfrog_id"),
            ("circles", Role, "glassfrog_circle_id"),
            ("accountabilities", Accountability, "glassfrog_id"),
            ("domains", Domain, "glassfrog_id"),
            ("policies", Policy, "glassfrog_id"),
        ]:
            for glassfrog_id, pk in model.objects.exclude(**{field: None}).values_list(
                field, "pk"
            ):
                ids[kind, glassfrog_id] = pk
        for proposal in data.get("proposals", []):
            links = proposal["links"]
            circle = self.circle(links.get("circle"), circles)
            if circle is None:
                self.stats["proposals without a known circle"] += 1
                continue
            tension = tensions.get(links.get("tension")) or {}
            decided_at = parse(proposal.get("accepted_at"))
            published_at = parse(proposal.get("proposed_at"))
            created_at = parse(tension.get("created_at")) or published_at or decided_at
            if created_at is None:
                self.stats["proposals without any date"] += 1
                continue
            day = (decided_at or created_at).date()
            status = PROPOSAL_STATUS.get(proposal["status"], Proposal.DRAFT)
            if (
                status == Proposal.IN_MEETING
                and proposal["id"] not in on_agenda
                and last_day
                and (published_at or created_at).date()
                < last_day - ESCALATED_STALE_AFTER
            ):
                status = Proposal.DRAFT
            instructions = proposal.get("instructions") or []
            names = self.names(instructions, day) | earlier.get(proposal["id"], {})
            if status != Proposal.ADOPTED:
                # The app adopts them: its own IDs. Adopted ones keep
                # GlassFrog's, their history stays as it was.
                app_instructions, names = to_app_ids(instructions, names, ids)
            else:
                app_instructions = instructions
            obj, _created = Proposal.objects.update_or_create(
                glassfrog_id=proposal["id"],
                defaults={
                    "circle": circle,
                    "proposer": self.users.get(links.get("person")),
                    "tension": tension.get("body") or tension.get("label") or "",
                    "instructions": app_instructions,
                    "names": names,
                    "status": status,
                    "created_at": created_at,
                    "published_at": published_at,
                    "deadline": parse(proposal.get("response_deadline")),
                    "decided_at": decided_at,
                    "glassfrog_tension_id": tension.get("id"),
                },
            )
            self.set_affected(obj, instructions)
            self.stats["proposals"] += 1

    def set_affected(self, proposal, instructions):
        """The roles and policies the proposal changes, for their history
        (from the instructions with GlassFrog's IDs)"""
        roles, policies = set(), set()
        circles = {
            role.glassfrog_circle_id: role
            for role in self.roles.values()
            if role.glassfrog_circle_id
        }
        for instruction in instructions:
            text = f"{instruction['path']} {instruction.get('from', '')}"
            for kind, value in PATH_OBJECTS.findall(text):
                glassfrog_id = int(value)
                if kind == "roles" and glassfrog_id in self.roles:
                    roles.add(self.roles[glassfrog_id])
                elif kind == "circles" and glassfrog_id in circles:
                    roles.add(circles[glassfrog_id])
                elif kind == "policies" and glassfrog_id in self.policies:
                    policies.add(self.policies[glassfrog_id])
        proposal.roles.set(roles)
        proposal.policies.set(policies)

    def import_tensions(self):
        data = self.files["tensions"]
        linked_circles = without_empty(data.get("linked", {}).get("circles"))
        for tension in data.get("tensions", []):
            links = tension["links"]
            if links.get("proposal"):
                continue  # Imported with its proposal
            circle = self.circle(links.get("circle"), linked_circles)
            if circle is None:
                self.stats["tensions without a known circle"] += 1
                continue
            Proposal.objects.update_or_create(
                glassfrog_tension_id=tension["id"],
                defaults={
                    "circle": circle,
                    "proposer": self.users.get(links.get("person")),
                    "tension": tension.get("body") or tension.get("label") or "",
                    "status": Proposal.DRAFT,
                    "created_at": parse(tension["created_at"]),
                },
            )
            self.stats["tensions"] += 1

    def import_meetings(self):
        proposals = {
            proposal.glassfrog_id: proposal
            for proposal in Proposal.objects.exclude(glassfrog_id=None)
        }
        for kind, name in [
            (Meeting.GOVERNANCE, "governance_meetings"),
            (Meeting.TACTICAL, "tactical_meetings"),
        ]:
            data = self.files[name]
            linked = data.get("linked", {})
            circles = without_empty(linked.get("circles"))
            items = defaultdict(list)
            for item in without_empty(linked.get("agenda_items")):
                items[item["links"]["meeting"]].append(item)

            for meeting_data in data.get(name, []):
                agenda = items.get(meeting_data["id"], [])
                circle = self.circle(meeting_data["links"].get("circle"), circles)
                meeting, _created = Meeting.objects.update_or_create(
                    kind=kind,
                    glassfrog_id=meeting_data["id"],
                    defaults={
                        "circle": circle,
                        "started_at": parse(meeting_data.get("started_at")),
                        "ended_at": parse(meeting_data.get("ended_at")),
                        "minutes": meeting_data.get("scratch_pad") or "",
                    },
                )
                self.stats[name] += 1
                if circle is None:
                    self.stats[f"{name} without a known circle"] += 1

                meeting.agenda_items.all().delete()
                AgendaItem.objects.bulk_create([
                    AgendaItem(
                        meeting=meeting,
                        position=item.get("position") or 0,
                        label=(item.get("label") or "")[:500],
                        owner=self.users.get(item["links"].get("person")),
                        proposal=proposals.get(item["links"].get("proposal")),
                        is_completed=bool(item.get("completed")),
                        glassfrog_id=item["id"],
                    )
                    for item in agenda
                ])
                if kind == Meeting.GOVERNANCE:
                    for item in agenda:
                        proposal = proposals.get(item["links"].get("proposal"))
                        if proposal and proposal.meeting_id != meeting.pk:
                            proposal.meeting = meeting
                            proposal.save(update_fields=["meeting"])

    def convert_mentions(self):
        """``@Role name`` in the current texts → ``@[Role name](role:ID)``"""
        # Earlier names and short names of the roles, texts may still use them
        aliases = {role.pk: role.other_names for role in self.roles.values()}
        # Also archived roles, after the current ones: texts mention removed roles
        resolver = self.resolver = MentionResolver(Role.objects.all(), aliases)
        for model, fields, context in [
            (Role, ["purpose", "strategy"], lambda obj: obj),
            (Accountability, ["text"], lambda obj: obj.role),
            (Domain, ["text"], lambda obj: obj.role),
            (Policy, ["body"], lambda obj: obj.role),
        ]:
            queryset = model.objects.all()
            if model is Role:
                queryset = queryset.filter(archived_on=None)
            for obj in queryset:
                changed = []
                for field in fields:
                    text = getattr(obj, field)
                    converted = resolver.convert(text, context(obj))
                    if converted != text:
                        setattr(obj, field, converted)
                        changed.append(field)
                if changed:
                    obj.save(update_fields=changed)
                    self.stats["texts with mentions"] += 1
        # The open proposals' texts too: the app adopts them, and their
        # original values have to match the converted current texts
        for proposal in (
            Proposal.objects
            .exclude(glassfrog_id=None)
            .exclude(status=Proposal.ADOPTED)
            .select_related("circle")
        ):
            instructions = [
                {
                    **instruction,
                    **{
                        key: resolver.convert(instruction[key], proposal.circle)
                        for key in ("value", "original_value")
                        if isinstance(instruction.get(key), str)
                    },
                }
                for instruction in proposal.instructions
            ]
            if instructions != proposal.instructions:
                proposal.instructions = instructions
                proposal.save(update_fields=["instructions"])
        for text in resolver.unresolved:
            self.log(f"Unresolved mention: @{text}")
        self.stats["unresolved mentions"] = len(resolver.unresolved)

    # History #################################################################

    def import_history(self):
        """GlassFrog's history as audit rows (``history.backfill``)

        The structure of every day in the app's format, keyed by the app's
        IDs, with the same mentions as in the database; the last day is the
        database's state, so that the audit log continues without
        differences. The audit rows replace this import's own rows and the
        history of an earlier import.
        """
        resolver = self.resolver
        unresolved = len(resolver.unresolved)
        cache = {}

        def convert(text, role_id):
            if not text or "@" not in text:
                return text
            key = (text, role_id)
            if key not in cache:
                cache[key] = resolver.convert(text, self.roles.get(role_id))
            return cache[key]

        users = {person_id: user.pk for person_id, user in self.users.items()}
        roles = {role_id: role.pk for role_id, role in self.roles.items()}
        policies = {policy_id: policy.pk for policy_id, policy in self.policies.items()}
        known = unknown = 0
        history = Backfill()
        for day, data in self.export.snapshots():
            snapshot = normalize(data)
            result = {"roles": {}, "policies": {}}
            for role_id, entry in snapshot["roles"].items():
                texts = [
                    self.accountability_texts.get(a) for a in entry["accountabilities"]
                ]
                known += sum(1 for text in texts if text is not None)
                unknown += sum(1 for text in texts if text is None)
                short_name = entry.get("short_name", "")
                result["roles"][str(roles[role_id])] = {
                    "name": entry["name"],
                    "purpose": convert(entry["purpose"], role_id),
                    "circle": roles.get(entry["circle"]),
                    "is_circle": entry["is_circle"],
                    "core_role": entry["core_role"],
                    "short_name": short_name if short_name != entry["name"] else "",
                    "strategy": convert(entry.get("strategy", ""), role_id),
                    "accountabilities": [convert(text, role_id) for text in texts],
                    "domains": [
                        convert(
                            snapshot["domains"].get(d) or self.domain_texts.get(d, ""),
                            role_id,
                        )
                        for d in entry["domains"]
                    ],
                    "assignments": [
                        {
                            "user": users[person_id],
                            "elected_until": entry["elected_until"],
                        }
                        for person_id in entry["people"]
                        if person_id in users
                    ],
                }
            for policy_id, entry in snapshot["policies"].items():
                if policy_id in policies and entry["role"] in roles:
                    result["policies"][str(policies[policy_id])] = {
                        "title": entry["title"],
                        "body": convert(entry["body"], entry["role"]),
                        "role": roles[entry["role"]],
                    }
            if day == self.history.days[-1]:
                result = structure_from_database(day)
            history.day(day, result)
            self.stats["history days"] += 1
        with connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM audit_logged_actions
                WHERE table_name = ANY(%s) AND (event_id > %s OR user_name = %s)
                """,
                [list(AUDIT_TABLES), self.first_event, BACKFILL_USER],
            )
        self.stats["history audit rows"] = history.save()
        del resolver.unresolved[unresolved:]
        total = known + unknown
        if total:
            self.stats["accountabilities in the history with a known text (%)"] = round(
                100 * known / total
            )


def import_glassfrog(path, **kwargs):
    return Importer(path, **kwargs).run()
