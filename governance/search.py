"""Searching the current governance

All terms have to match (case-insensitive, ignoring accents) the texts as
the pages show them: mentions with the roles' current names, the core
roles with the constitution's texts. The data is small enough for
searching in Python, no full text index needed.
"""

import unicodedata
from types import SimpleNamespace

from django.shortcuts import render

from governance.roles.mentions import MENTION
from governance.roles.models import Accountability, Domain, Policy, Role


LIMIT = 50


def _fold(text):
    """Without accents and case"""
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", str(text))
        if not unicodedata.combining(c)
    ).casefold()


def search_results(query):
    """Matching roles, accountabilities, domains and policies (50 each)"""
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

    roles = list(Role.objects.active().select_related("circle").order_by("pk"))

    def texts_of(model, kind):
        """The role's own and the constitution's"""
        own = list(
            model.objects
            .filter(role__archived_on=None)
            .select_related("role__circle")
            .order_by("pk")
        )
        constitutional = [
            SimpleNamespace(pk=None, text=str(text), role=role, role_id=role.pk)
            for role in roles
            if role.core
            for text in getattr(role.core, kind)
        ]
        return constitutional + own

    return {
        "roles": matching(
            roles, lambda role: [role.name, role.display_purpose, role.strategy]
        ),
        "accountabilities": matching(
            texts_of(Accountability, "accountabilities"), lambda item: [item.text]
        ),
        "domains": matching(texts_of(Domain, "domains"), lambda item: [item.text]),
        "policies": matching(
            Policy.objects.active().select_related("role").order_by("pk"),
            lambda policy: [policy.title, policy.body],
        ),
    }


def search(request):
    query = request.GET.get("q", "").strip()
    results = search_results(query)
    return render(
        request,
        "search/search.html",
        {
            "query": query,
            "results": results,
            "empty": bool(query.split()) and not any(results.values()),
        },
    )
