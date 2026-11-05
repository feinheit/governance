"""The 404 page, telling proposers about their deleted drafts

Roles and policies are archived, not deleted, and people who left stay as
inactive users: drafts of proposals are the only pages which disappear.
Drafts are private, so only their proposer learns about the deletion (an
existing draft of somebody else is a 404 too).
"""

from django.shortcuts import render
from django.urls import Resolver404, resolve

from governance.audit.models import LoggedAction
from governance.proposals.models import Proposal


def deleted_draft(request):
    try:
        match = resolve(request.path_info)
    except Resolver404:
        return None
    if match.url_name != "proposal" or not request.user.is_authenticated:
        return None
    return (
        LoggedAction.objects
        .for_model(Proposal)
        .filter(
            action="D",
            row_data__id=str(match.kwargs["pk"]),
            row_data__proposer_id=str(request.user.pk),
        )
        .order_by("-created_at")
        .first()
    )


def page_not_found(request, exception):
    deleted = deleted_draft(request)
    return render(
        request,
        "404.html",
        {
            "deleted_on": deleted.created_at if deleted else None,
            "deleted_tension": deleted.row_data.get("tension", "") if deleted else "",
        },
        status=404,
    )
