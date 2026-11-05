"""Who runs a meeting and who adds agenda items"""

from governance.roles.models import Assignment
from governance.roles.permissions import can_start_meeting, is_member


def can_run(user, meeting):
    """The circle's members (standing in for the Facilitator and Secretary if
    needed), the meeting's facilitator and secretary (also when they aren't
    members), and for tactical meetings whoever called it"""
    if user.is_admin:
        return True
    if meeting.circle and can_start_meeting(user, meeting.circle):
        return True
    return user.pk in {
        meeting.called_by_id,
        meeting.facilitator_id,
        meeting.secretary_id,
    }


def can_add_items(user, meeting):
    """Everybody in the meeting builds the agenda, in the meeting (constitution
    5.4.4)"""
    if not meeting.is_running:
        return False
    return (
        can_run(user, meeting)
        or meeting.attendees.filter(pk=user.pk).exists()
        or (meeting.circle is not None and is_member(user, meeting.circle))
        or Assignment.objects
        .current()
        .filter(user=user, role__in=meeting.invited_roles.all())
        .exists()
    )
