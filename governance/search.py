"""Searching the current governance and the people

All terms have to match (case-insensitive, ignoring accents) the texts as
the pages show them: mentions with the roles' current names, the core
roles with the constitution's texts, the active people's names, short
names and mail addresses, the links of active roles by their titles and
descriptions (which may hold keywords: the handbook's sections are found
this way), their notes by titles and bodies, their checklist items and
metrics by descriptions. With ``archived`` also archived roles (with
their texts, links, notes, checklist items and metrics), archived policies
and inactive people, after the current ones. The data is small enough for
searching in Python, no full text index needed.
"""

import unicodedata
from types import SimpleNamespace

from django.db.models import F
from django.shortcuts import render

from governance.accounts.models import User
from governance.roles.mentions import MENTION
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
from governance.roles.permissions import held_as_circle_lead


LIMIT = 50


def _fold(text):
    """Without accents and case"""
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", str(text))
        if not unicodedata.combining(c)
    ).casefold()


def search_results(query, *, archived=False):
    """Matching people (with their ``circles``), roles, accountabilities,
    domains, policies, links, notes, checklist items and metrics (50 each,
    the current ones first)"""
    terms = [_fold(term) for term in query.split()]
    if not terms:
        return {}
    names = dict(Role.objects.values_list("pk", "name"))

    def shown(text):
        return MENTION.sub(
            lambda match: f"@{names.get(int(match[2]), match[1])}", str(text or "")
        )

    def matching(objects, texts):
        found = []
        for obj in objects:
            text = _fold(" ".join(shown(t) for t in texts(obj)))
            if all(term in text for term in terms):
                found.append(obj)
                if len(found) == LIMIT:
                    break
        return found

    current_first = F("archived_on").asc(nulls_first=True)
    roles = list(
        (Role.objects.all() if archived else Role.objects.active())
        .select_related("circle")
        .order_by(current_first, "pk")
    )

    def of_roles(model):
        """Of the roles searched, those of current roles first"""
        items = (
            model.objects.all()
            if archived
            else model.objects.filter(role__archived_on=None)
        )
        return items.select_related("role__circle").order_by(
            F("role__archived_on").asc(nulls_first=True), "pk"
        )

    def texts_of(model, kind):
        """The role's own and the constitution's"""
        own = list(of_roles(model))
        constitutional = [
            SimpleNamespace(pk=None, text=str(text), role=role, role_id=role.pk)
            for role in roles
            if role.core
            for text in getattr(role.core, kind)
        ]
        # Stable: the current roles' first in both
        return sorted(
            constitutional + own, key=lambda item: bool(item.role.archived_on)
        )

    return {
        "people": with_circles(
            matching(
                (User.objects.all() if archived else User.objects.active()).order_by(
                    "-is_active", "pk"
                ),
                lambda user: [user.full_name, user.short_name, user.email],
            )
        ),
        "roles": matching(
            roles, lambda role: [role.name, role.display_purpose, role.strategy]
        ),
        "accountabilities": matching(
            texts_of(Accountability, "accountabilities"), lambda item: [item.text]
        ),
        "domains": matching(texts_of(Domain, "domains"), lambda item: [item.text]),
        "policies": matching(
            (Policy.objects.all() if archived else Policy.objects.active())
            .select_related("role")
            .order_by(current_first, "pk"),
            lambda policy: [policy.title, policy.body],
        ),
        "links": matching(
            of_roles(Link),
            lambda link: [link.title, link.description],
        ),
        "notes": matching(
            of_roles(Note),
            lambda note: [note.title, note.body],
        ),
        **{
            key: matching(
                of_roles(model),
                lambda item: [item.description],
            )
            for key, model in [
                ("checklist_items", ChecklistItem),
                ("metrics", Metric),
            ]
        },
    }


def with_circles(people):
    """The circles whose roles the people hold or fill, in the
    organization's order"""
    order = {
        circle.pk: index for index, circle in enumerate(Role.objects.depth_first())
    }
    circles = {person.pk: {} for person in people}
    for assignment in (
        Assignment.objects
        .current()
        .filter(user__in=people, role__archived_on=None, role__circle__isnull=False)
        .select_related("role__circle")
    ):
        circle = assignment.role.circle
        circles[assignment.user_id][circle.pk] = circle
    for person in people:
        # Also those filled without being assigned (1.4.2, 5.3.6)
        for role in held_as_circle_lead(person):
            circles[person.pk][role.circle_id] = role.circle
        person.circles = sorted(
            circles[person.pk].values(), key=lambda c: order.get(c.pk, len(order))
        )
    return people


def search(request):
    query = request.GET.get("q", "").strip()
    archived = bool(request.GET.get("archived"))
    results = search_results(query, archived=archived)
    return render(
        request,
        "search/search.html",
        {
            "query": query,
            "archived": archived,
            "results": results,
            "empty": bool(query.split()) and not any(results.values()),
        },
    )
