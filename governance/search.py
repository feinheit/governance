"""Searching the current governance

All terms have to match (case-insensitive, ignoring accents). The data is
small enough for this, no full text index needed.
"""

from functools import reduce
from operator import and_

from django.db.models import Q
from django.shortcuts import render

from governance.roles.models import Accountability, Domain, Policy, Role


def _matching(queryset, fields, terms):
    return queryset.filter(
        reduce(
            and_,
            [
                reduce(
                    lambda a, b: a | b,
                    [Q(**{f"{field}__unaccent__icontains": term}) for field in fields],
                )
                for term in terms
            ],
        )
    )


def search_results(query):
    """Matching roles, accountabilities, domains and policies (50 each)"""
    terms = query.split()
    if not terms:
        return {}
    return {
        "roles": _matching(
            Role.objects.active(), ["name", "purpose", "strategy"], terms
        ).select_related("circle")[:50],
        "accountabilities": _matching(
            Accountability.objects.filter(role__archived_on=None), ["text"], terms
        ).select_related("role__circle")[:50],
        "domains": _matching(
            Domain.objects.filter(role__archived_on=None), ["text"], terms
        ).select_related("role__circle")[:50],
        "policies": _matching(
            Policy.objects.active(), ["title", "body"], terms
        ).select_related("role")[:50],
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
