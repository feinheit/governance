"""Who runs a meeting and who adds agenda items"""

from governance.roles.models import Assignment
from governance.roles.permissions import ALLOWED, NOT_ALLOWED, as_admin, is_member


def can_run(user, meeting):
    """The meeting's secretary handles its buttons: the steps, processing
    items, adopting, the attendees, ending it. The others follow; those who
    may take over do so first (can_take_over())."""
    if meeting.secretary_id is not None and meeting.secretary_id == user.pk:
        return ALLOWED
    return NOT_ALLOWED


def can_take_over(user, meeting):
    """Who takes over as the meeting's secretary (e.g. standing in, 5.3.6):
    the circle's members, the meeting's secretary (also when they aren't a
    member), and for tactical meetings whoever called it"""
    if meeting.circle and is_member(user, meeting.circle):
        return ALLOWED
    if user.pk in {meeting.called_by_id, meeting.secretary_id}:
        return ALLOWED
    return as_admin(user)


def can_add_items(user, meeting):
    """Everybody in the meeting builds the agenda, in the meeting (constitution
    5.4.4)"""
    if not meeting.is_running:
        return False
    # The members (can_take_over()), attendees and invited roles add items
    return (
        can_take_over(user, meeting)
        or meeting.attendees.filter(pk=user.pk).exists()
        or Assignment.objects
        .current()
        .filter(user=user, role__in=meeting.invited_roles.all())
        .exists()
    )
