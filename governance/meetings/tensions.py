"""The circles' tension inboxes: tensions noted before a meeting, put on its
agenda by their owners or the meeting's secretary

The circle's members see the inbox and add to it, private tensions only
their owners. A tension on an agenda
leaves the inbox; removing the item or ending the meeting without
processing it puts it back (``return_to_inbox()``), also items typed in
the meeting.
"""

import datetime as dt

from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import Truncator
from django.utils.translation import gettext, gettext_lazy as _

from governance.forms import ModelForm, next_url
from governance.meetings.access import can_add_items, can_run
from governance.meetings.models import AgendaItem, Meeting, Tension
from governance.roles.models import Role
from governance.roles.permissions import (
    ALLOWED,
    acting_secretaries,
    as_admin,
    is_member,
)


# Tensions in the inbox longer are collapsed
OLDER = dt.timedelta(days=91)


def can_use_inbox(user, circle):
    """The circle's members see its inbox and add to it"""
    if circle is None or not circle.is_circle or circle.archived_on:
        return ""
    if is_member(user, circle):
        return ALLOWED
    return as_admin(user)


def can_change(user, tension):
    """Its owner changes or deletes it while it's in the inbox"""
    if tension.agenda_item_id is not None or tension.proposal_id is not None:
        return ""
    if tension.owner_id == user.pk:
        return ALLOWED
    return as_admin(user)


def can_delete(user, tension):
    """Its owner deletes it while it's in the inbox, the circle's acting
    Secretary once the owner isn't a member anymore (not private ones)"""
    if right := can_change(user, tension):
        return right
    if (
        tension.agenda_item_id is None
        and tension.proposal_id is None
        and not tension.is_private
    ):
        circle = tension.circle
        if (
            not is_member(tension.owner, circle)
            and acting_secretaries(circle).filter(pk=user.pk).exists()
        ):
            return ALLOWED
    return ""


def split_older(tensions):
    """The inbox's tensions, newest first, and those older than three
    months (collapsed)"""
    cutoff = timezone.now() - OLDER
    tensions = sorted(tensions, key=lambda t: t.created_at, reverse=True)
    return (
        [t for t in tensions if t.created_at >= cutoff],
        [t for t in tensions if t.created_at < cutoff],
    )


def inbox(user, meeting):
    """The tensions of the circle's inbox the user puts on the meeting's
    agenda: their own, the secretary's those of the attendees (who were
    invited rather than who is there), grouped by owner. The agenda is
    built in the meeting by its participants (constitution 3.x, 5.4.4):
    the inbox only notes tensions, the secretary adds a person's when they
    name them"""
    if not meeting.circle or not can_add_items(user, meeting):
        return Tension.objects.none()
    tensions = (
        meeting.circle.tensions
        .open()
        .select_related("owner")
        .order_by("owner__full_name", "owner__email", "created_at")
    )
    if can_run(user, meeting):
        # Private ones only their owners
        return tensions.filter(
            Q(owner=user) | Q(owner__in=meeting.attendees.all(), is_private=False)
        )
    return tensions.filter(owner=user)


def return_to_inbox(meeting):
    """The agenda's items left unprocessed when the meeting ends go into the
    circle's inbox, those of proposals wait for the next meeting anyway,
    elections are added again while they're due"""
    items = meeting.agenda_items.filter(
        is_completed=False, proposal=None, is_election=False
    )
    # Typed in the meeting (ad hoc tactical meetings have no inbox)
    typed = (
        list(items.filter(tension=None).exclude(owner=None).exclude(label=""))
        if meeting.circle
        else []
    )
    Tension.objects.filter(agenda_item__in=items).update(agenda_item=None)
    for item in typed:
        Tension.objects.create(
            circle=meeting.circle, owner=item.owner, title=item.label[:200]
        )


class TensionForm(ModelForm):
    class Meta:
        model = Tension
        fields = ["title", "description", "is_private"]


def _done(request, circle):
    # Without a fragment: in a modal on the circle's page only changing the
    # fragment wouldn't reload the page (HX-Redirect), the modal stayed open
    return redirect(next_url(request) or circle)


def tension_form(request, pk=None, circle_pk=None):
    if pk:
        tension = get_object_or_404(Tension.objects.select_related("circle"), pk=pk)
        circle = tension.circle
        right = can_change(request.user, tension)
    else:
        circle = get_object_or_404(Role, pk=circle_pk)
        tension = Tension(circle=circle, owner=request.user)
        right = can_use_inbox(request.user, circle)
    if not right:
        raise PermissionDenied
    form = TensionForm(request.POST or None, instance=tension)
    if form.is_valid():
        form.save()
        return _done(request, circle)
    return render(
        request,
        "generic/object_form.html",
        {
            "title": gettext("Tension for %(circle)s") % {"circle": circle},
            "help": gettext(
                "In the circle's inbox, its members see it. You or the"
                " secretary put it on the agenda of a meeting, or you draft a"
                " proposal from it, private until published."
            ),
            "form": form,
            "right": right,
            "cancel_url": next_url(request) or circle.get_absolute_url(),
        },
    )


def tension_delete(request, pk):
    tension = get_object_or_404(
        Tension.objects.select_related("circle", "owner"), pk=pk
    )
    if not (right := can_delete(request.user, tension)):
        raise PermissionDenied
    if request.method == "POST":
        tension.delete()
        return _done(request, tension.circle)
    return render(
        request,
        "generic/confirm.html",
        {
            "question": gettext("Delete this tension?"),
            "help": tension.circle,
            "text": tension,
            "submit_label": gettext("Delete"),
            "right": right,
            "cancel_url": tension.circle.get_absolute_url(),
        },
    )


def agenda_tensions(request, pk):
    """Putting tensions of the circle's inbox on the agenda (a modal with
    checkboxes)"""
    meeting = get_object_or_404(Meeting.objects.select_related("circle"), pk=pk)
    if not can_add_items(request.user, meeting) or not meeting.circle:
        raise PermissionDenied
    tensions = inbox(request.user, meeting)
    if request.method == "POST":
        selected = tensions.filter(
            pk__in=[v for v in request.POST.getlist("tensions") if v.isdigit()]
        )
        last = max((item.position for item in meeting.agenda_items.all()), default=0)
        for position, tension in enumerate(selected, last + 1):
            tension.agenda_item = AgendaItem.objects.create(
                meeting=meeting,
                position=position,
                owner=tension.owner,
                label=Truncator(tension.title).chars(500),
            )
            tension.save(update_fields=["agenda_item"])
        return redirect(meeting)
    return render(
        request,
        "meetings/agenda_tensions.html",
        {
            "meeting": meeting,
            "tensions": tensions,
            "title": _("From the inbox"),
        },
    )
