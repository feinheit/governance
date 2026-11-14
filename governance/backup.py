"""The JSON backup: everything the user sees, organized by role

``GET /api/backup/`` (``gov backup``): ``roles``, all of them (archived
ones too) ordered by ID, each with its circle's ID and what belongs to it:
texts, policies (with their history), Role Leads (past ones too), metrics,
checklist items, links, notes, its history (the day-to-day changes since 2018)
and the proposals and meetings it's the circle of; ``meetings`` without a
circle (ad hoc tactical meetings); ``people`` only when asked for
(``?people=true``), the rest refers to them by ID. ``gov backup DIR``
writes a file per role, ``scripts/fetch_backup.py`` commits them daily.
The models' field names, see section 8 of ``SPEC.md``.
"""

from collections import defaultdict

from governance.accounts.models import User
from governance.history.models import Change
from governance.meetings.models import AgendaItem, Election, Meeting
from governance.proposals.models import Proposal, Response
from governance.roles.models import (
    Accountability,
    Assignment,
    ChecklistItem,
    Domain,
    Link,
    Metric,
    Note,
    Policy,
    Role,
)


def rows(queryset, *fields):
    return list(queryset.order_by("pk").values("id", *fields))


def by(key, items):
    grouped = defaultdict(list)
    for item in items:
        grouped[item.pop(key)].append(item)
    return grouped


def related(manager, key, value):
    """``{id: [IDs]}`` of a many-to-many field"""
    grouped = defaultdict(list)
    for pk, other in manager.through.objects.order_by(value).values_list(key, value):
        grouped[pk].append(other)
    return grouped


def nest(objects, **children):
    for obj in objects:
        for name, grouped in children.items():
            obj[name] = grouped.get(obj["id"], [])
    return objects


def history(key, **filters):
    """The day-to-day changes, grouped by role or policy (``key``)"""
    return by(
        key,
        list(
            Change.objects
            .filter(**filters)
            .order_by("date", "pk")
            .values(key, "date", "kind", "old", "new")
        ),
    )


def roles(user):
    texts = {
        name: by(
            "role",
            rows(model.objects.all(), "role", "text", "position", "glassfrog_id"),
        )
        for name, model in [("accountabilities", Accountability), ("domains", Domain)]
    }
    items = [
        "role",
        "description",
        "frequency",
        "link",
        "position",
        "whole_circle",
        "glassfrog_id",
    ]
    policies = nest(
        rows(
            Policy.objects.all(),
            "role",
            "domain",
            "title",
            "body",
            "position",
            "archived_on",
            "glassfrog_id",
        ),
        history=history("policy", policy__isnull=False),
    )
    return nest(
        rows(
            Role.objects.all(),
            "circle",
            "name",
            "short_name",
            "purpose",
            "strategy",
            "position",
            "core_role",
            "is_circle",
            "is_elected_by_policy",
            "async_acceptance_days",
            "archived_on",
            "glassfrog_id",
        ),
        **texts,
        policies=by("role", policies),
        role_leads=by(
            "role",
            rows(
                Assignment.objects.all(),
                "role",
                "user",
                "focus",
                "elected_until",
                "starts_on",
                "ends_on",
                "glassfrog_id",
            ),
        ),
        metrics=by("role", rows(Metric.objects.all(), *items)),
        checklist_items=by("role", rows(ChecklistItem.objects.all(), *items)),
        links=by(
            "role",
            rows(Link.objects.all(), "role", "title", "url", "description", "position"),
        ),
        notes=by(
            "role",
            rows(Note.objects.all(), "role", "title", "body", "position"),
        ),
        history=history("role", role__isnull=False, policy__isnull=True),
        proposals=by("circle", proposals(user)),
        meetings=by("circle", [m for m in meetings() if m["circle"]]),
    )


def proposals(user):
    visible = Proposal.objects.visible_to(user)
    return nest(
        rows(
            visible,
            "circle",
            "role",
            "proposer",
            "status",
            "tension",
            "instructions",
            "names",
            "created_at",
            "published_at",
            "deadline",
            "decided_at",
            "meeting",
            "glassfrog_id",
            "adopted_in_glassfrog",
        ),
        affected_roles=related(Proposal.roles, "proposal_id", "role_id"),
        affected_policies=related(Proposal.policies, "proposal_id", "policy_id"),
        responses=by("proposal", responses(visible)),
    )


def responses(proposals):
    """Anonymous like on the proposal page (``process.response_summary()``):
    only questions and concerns have their author"""
    result = rows(
        Response.objects.filter(proposal__in=proposals),
        "proposal",
        "user",
        "kind",
        "text",
        "created_at",
    )
    for row in result:
        # Consents (earlier ones had texts) and requests without a concern
        if row["kind"] == Response.CONSENT or (
            row["kind"] != Response.COMMENT and not row["text"]
        ):
            row["user"] = None
    return result


def meetings():
    return nest(
        rows(
            Meeting.objects.all(),
            "circle",
            "kind",
            "started_at",
            "ended_at",
            "secretary",
            "called_by",
            "minutes",
            "glassfrog_id",
        ),
        attendees=related(Meeting.attendees, "meeting_id", "user_id"),
        invited_roles=related(Meeting.invited_roles, "meeting_id", "role_id"),
        agenda=by(
            "meeting",
            rows(
                AgendaItem.objects.all(),
                "meeting",
                "position",
                "label",
                "owner",
                "proposal",
                "is_completed",
                "outcome",
                "link",
            ),
        ),
        elections=by(
            "meeting",
            rows(
                Election.objects.all(),
                "meeting",
                "role",
                "user",
                "term_ends_on",
                "created_at",
            ),
        ),
    )


def backup(user, *, with_people=False):
    """What ``user`` sees (not others' drafts); the people only when asked
    for, personal data"""
    data = {
        "roles": roles(user),
        "meetings": [
            {key: value for key, value in m.items() if key != "circle"}
            for m in meetings()
            if not m["circle"]
        ],
    }
    if with_people:
        data["people"] = rows(
            User.objects.all(),
            "full_name",
            "short_name",
            "email",
            "is_active",
            "glassfrog_id",
        )
    return data
