"""Who is using the API, e.g. for gov me and choosing the role of a proposal"""

from django.conf import settings
from ninja import Router, Schema

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
