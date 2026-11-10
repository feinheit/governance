"""When running meetings were last active, and ending the inactive ones

Changes to the meeting, its attendees, agenda and elections
and to the proposals processed in it are activity; following it on the
screen isn't. Nobody has to remember to end a meeting: hourly_tasks ends
those inactive for hours, starting a meeting in the circle too.
"""

import datetime as dt
from functools import partial

from django.db import transaction
from django.db.models import Q
from django.db.models.signals import m2m_changed, post_delete, post_save
from django.utils import timezone

from governance.meetings.models import AgendaItem, Election, Meeting
from governance.notifications import mails
from governance.proposals.models import Proposal


INACTIVITY = dt.timedelta(hours=3)


def touch(meetings):
    meetings.running().update(active_at=timezone.now())


def meeting_changed(sender, instance, **kwargs):
    touch(Meeting.objects.filter(pk=instance.pk))


def part_changed(sender, instance, **kwargs):
    touch(Meeting.objects.filter(pk=instance.meeting_id))


def proposal_changed(sender, instance, **kwargs):
    touch(
        Meeting.objects.filter(
            Q(pk=instance.meeting_id) | Q(agenda_items__proposal=instance)
        )
    )


def connect():
    post_save.connect(meeting_changed, sender=Meeting)
    m2m_changed.connect(meeting_changed, sender=Meeting.attendees.through)
    for model in [AgendaItem, Election]:
        post_save.connect(part_changed, sender=model)
        post_delete.connect(part_changed, sender=model)
    post_save.connect(proposal_changed, sender=Proposal)


def end_meeting(meeting, at=None):
    """Ends the meeting, its outputs go out by mail; a circle which lost its
    last roles in it turns back into a role now"""
    from governance.meetings.elections import announce_elections
    from governance.proposals.instructions import revert_after_meeting

    meeting.ended_at = at or timezone.now()
    meeting.current_item = None
    meeting.save(update_fields=["ended_at", "current_item"])
    # Not the elections of core roles archived by turning back
    revert_after_meeting(meeting)
    announce_elections(meeting)
    transaction.on_commit(partial(mails.meeting_ended, meeting))


def end_inactive_meetings(meetings=None):
    """Ends the meetings inactive for hours with their last activity"""
    cutoff = timezone.now() - INACTIVITY
    if meetings is None:
        meetings = Meeting.objects.all()
    inactive = meetings.running().filter(
        Q(active_at__lt=cutoff) | Q(active_at=None, started_at__lt=cutoff)
    )
    count = 0
    for meeting in inactive:
        end_meeting(meeting, meeting.active_at or meeting.started_at)
        count += 1
    return count
