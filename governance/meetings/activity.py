"""When running meetings were last active, and ending the inactive ones

Changes to the meeting, its attendees, agenda, objections and elections
and to the proposals processed in it are activity; following it on the
screen isn't. Nobody has to remember to end a meeting: fairy_tasks ends
those inactive for hours, starting a meeting in the circle too.
"""

import datetime as dt

from django.db import transaction
from django.db.models import Q
from django.db.models.signals import m2m_changed, post_delete, post_save
from django.utils import timezone

from governance.meetings.models import AgendaItem, Election, Meeting, Objection
from governance.notifications.mails import meeting_ended
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
    for model in [AgendaItem, Objection, Election]:
        post_save.connect(part_changed, sender=model)
        post_delete.connect(part_changed, sender=model)
    post_save.connect(proposal_changed, sender=Proposal)


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
        meeting.ended_at = meeting.active_at or meeting.started_at
        meeting.current_item = None
        meeting.save(update_fields=["ended_at", "current_item"])
        transaction.on_commit(lambda meeting=meeting: meeting_ended(meeting))
        count += 1
    return count
