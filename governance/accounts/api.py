"""Who is using the API, e.g. for gov me and choosing the role of a proposal,
and their API tokens (gov tokens, gov logout)"""

import datetime as dt
from typing import Literal

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext as _
from ninja import Field, Router, Schema
from ninja.errors import HttpError

from governance.accounts.api_auth import user_auth
from governance.accounts.models import APIToken
from governance.roles.models import Assignment, Role


router = Router(tags=["accounts"])


class MyRoleOut(Schema):
    id: int
    name: str
    circle_id: int | None
    circle: str
    focus: str
    url: str


class MeOut(Schema):
    id: int
    name: str
    short_name: str
    email: str
    url: str
    access: str
    roles: list[MyRoleOut]


@router.get("me/", response=MeOut)
def me(request):
    """The authenticated user, the access of the token and their roles in
    the organization's order (depth-first through the circles)"""
    user = request.user
    circles = {
        circle.pk: index for index, circle in enumerate(Role.objects.depth_first())
    }
    assignments = sorted(
        Assignment.objects
        .current()
        .filter(user=user, role__archived_on=None)
        .select_related("role__circle"),
        key=lambda a: (circles.get(a.role.circle_id, -1), a.role.position, a.role.name),
    )
    return {
        "id": user.pk,
        "name": user.get_full_name(),
        "short_name": user.get_short_name(),
        "email": user.email,
        "url": settings.BASE_URL + user.get_absolute_url(),
        "access": token.access
        if (token := getattr(request, "api_token", None))
        else "write",
        "roles": [
            {
                "id": assignment.role_id,
                "name": assignment.role.name,
                "circle_id": assignment.role.circle_id,
                "circle": str(assignment.role.circle or ""),
                "focus": assignment.focus,
                "url": settings.BASE_URL + assignment.role.get_absolute_url(),
            }
            for assignment in assignments
        ],
    }


class APITokenOut(Schema):
    id: int
    title: str
    access: Literal["read", "write"]
    access_label: str
    created_at: dt.datetime
    last_used_at: dt.datetime | None
    expires_at: dt.datetime
    current: bool = Field(
        description="Whether this is the token which authenticated the request."
    )


def api_token_out(token, request):
    current = getattr(request, "api_token", None)
    return {
        "id": token.id,
        "title": token.title,
        "access": token.access,
        "access_label": token.get_access_display(),
        "created_at": token.created_at,
        "last_used_at": token.last_used_at,
        "expires_at": token.expires_at,
        "current": bool(current and current.pk == token.pk),
    }


@router.get("tokens/", response=list[APITokenOut])
def api_token_list(request):
    """The authenticated user's API tokens which haven't expired yet"""
    return [
        api_token_out(token, request)
        for token in request.user.api_tokens.filter(expires_at__gt=timezone.now())
    ]


@router.delete(
    "tokens/current/", response=APITokenOut, auth=user_auth(allow_read_only=True)
)
def api_token_delete_current(request):
    """Revoke the API token which authenticated the request, e.g. when logging
    out; read only tokens may do this too. Returns the deleted token."""
    if not (token := getattr(request, "api_token", None)):
        raise HttpError(400, _("This request wasn't authenticated with a token."))
    result = api_token_out(token, request)
    token.delete()
    return result


@router.delete(
    "tokens/{token_id}/", response=APITokenOut, auth=user_auth(allow_read_only=True)
)
def api_token_delete(request, token_id: int):
    """Revoke one of the authenticated user's API tokens immediately, e.g.
    one which isn't needed anymore or has leaked

    Read only tokens may only revoke themselves. Returns the deleted token."""
    token = get_object_or_404(request.user.api_tokens, pk=token_id)
    current = getattr(request, "api_token", None)
    if current and current.access == APIToken.Access.READ and current.pk != token.pk:
        raise HttpError(403, _("This API token only allows reading, not changes."))
    result = api_token_out(token, request)
    token.delete()
    return result
