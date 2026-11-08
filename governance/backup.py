"""The JSON backup: everything the user sees, one file per kind

``GET /api/backup/`` returns the files, ``scripts/fetch_backup.py`` commits
them daily to a git repository, like the GlassFrog export before. Lists of
objects ordered by ID, with the models' field names; related objects by ID
(``user`` refers to ``people.json``). See section 8 of ``SPEC.md``.
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


def roles():
    texts = {
        name: by(
            "role",
            rows(model.objects.all(), "role", "text", "position", "glassfrog_id"),
        )
        for name, model in [("accountabilities", Accountability), ("domains", Domain)]
    }
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


def backup(user):
    """The files of the backup, what ``user`` sees (not others' drafts)"""
    items = ["role", "description", "frequency", "link", "position", "glassfrog_id"]
    return {
        "people.json": rows(
            User.objects.all(),
            "full_name",
            "short_name",
            "email",
            "is_active",
            "glassfrog_id",
        ),
        "roles.json": roles(),
        "assignments.json": rows(
            Assignment.objects.all(),
            "role",
            "user",
            "focus",
            "elected_until",
            "starts_on",
            "ends_on",
            "glassfrog_id",
        ),
        "policies.json": rows(
            Policy.objects.all(),
            "role",
            "domain",
            "title",
            "body",
            "position",
            "archived_on",
            "glassfrog_id",
        ),
        # The day-to-day changes, since 2018 from GlassFrog's history
        "history.json": rows(
            Change.objects.all(), "date", "role", "policy", "kind", "old", "new"
        ),
        "proposals.json": proposals(user),
        "meetings.json": meetings(),
        "metrics.json": rows(Metric.objects.all(), *items),
        "checklist_items.json": rows(ChecklistItem.objects.all(), *items),
        "links.json": rows(
            Link.objects.all(), "role", "title", "url", "description", "position"
        ),
    }
