"""Mails to the subscribers of circles, see section 5 of SPEC.md"""

from django.conf import settings
from django.core.mail import EmailMessage
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils.translation import gettext as _, override

from governance.accounts.models import User
from governance.proposals.describe import describe
from governance.roles.permissions import members


def recipients(circle):
    """The circle's members, and everybody who wants to know everything"""
    return User.objects.active().filter(Q(pk__in=members(circle)) | Q(notify_all=True))


def send(users, subject, template, context):
    """One mail per user, in their language; nothing for people who left"""
    sent = 0
    for user in users.filter(is_active=True).distinct():
        with override(user.language or settings.LANGUAGE_CODE):
            EmailMessage(
                subject=str(subject()),
                body=render_to_string(template, context | {"user": user}),
                to=[user.email],
            ).send()
        sent += 1
    return sent


def proposal_context(proposal):
    return {
        "proposal": proposal,
        "changes": describe(proposal.instructions, proposal.names),
        "url": settings.BASE_URL + proposal.get_absolute_url(),
    }


def everybody(proposal):
    """The recipients and the proposer, e.g. an admin who isn't a member"""
    return User.objects.filter(
        Q(pk__in=recipients(proposal.circle)) | Q(pk=proposal.proposer_id)
    )


def proposal_published(proposal):
    return send(
        everybody(proposal),
        lambda: (
            _("Proposal in %(circle)s: %(proposal)s")
            % {"circle": proposal.circle, "proposal": proposal}
        ),
        "notifications/proposal_published.txt",
        proposal_context(proposal),
    )


def proposal_back_to_draft(proposal):
    return send(
        everybody(proposal),
        lambda: (
            _("Back to the draft in %(circle)s: %(proposal)s")
            % {"circle": proposal.circle, "proposal": proposal}
        ),
        "notifications/proposal_back_to_draft.txt",
        proposal_context(proposal),
    )


def proposal_adopted(proposal, members_before=()):
    """``members_before``: the members when adopting began, e.g. the holders
    of roles the proposal removed or moved away"""
    return send(
        everybody(proposal) | User.objects.active().filter(pk__in=members_before),
        lambda: (
            _("Adopted in %(circle)s: %(proposal)s")
            % {"circle": proposal.circle, "proposal": proposal}
        ),
        "notifications/proposal_adopted.txt",
        proposal_context(proposal),
    )


def domain_policy_changed(proposal):
    """A role changed a policy for its domains: everybody affected, the
    members of its circle and all sub-circles"""
    circles, pending = [], [proposal.circle]
    while pending:
        circle = pending.pop()
        circles.append(circle)
        pending.extend(circle.roles.active().circles())
    users = User.objects.filter(
        Q(pk__in=User.objects.active().filter(notify_all=True))
        | Q(pk=proposal.proposer_id)
        | Q(pk__in=[user.pk for circle in circles for user in members(circle)])
    )
    return send(
        users,
        lambda: (
            _("Policy of %(role)s changed: %(policy)s")
            % {"role": proposal.role, "policy": next(iter(proposal.names.values()), "")}
        ),
        "notifications/domain_policy_changed.txt",
        proposal_context(proposal),
    )


def elections_due(day=None):
    """The weekly reminder to the Secretaries about terms ending soon"""
    from collections import defaultdict

    from governance.meetings.elections import due_elections
    from governance.roles.models import Assignment, Role

    by_secretary = defaultdict(list)
    for circle in Role.objects.active().circles():
        if not (due := due_elections([circle], day=day)):
            continue
        for assignment in Assignment.objects.current(on=day).filter(
            role__circle=circle, role__core_role="secretary", role__archived_on=None
        ):
            by_secretary[assignment.user_id].extend(due)
    sent = 0
    for user in User.objects.active().filter(pk__in=by_secretary):
        sent += send(
            User.objects.filter(pk=user.pk),
            lambda: _("Elections due"),
            "notifications/elections_due.txt",
            {"due": by_secretary[user.pk], "base_url": settings.BASE_URL},
        )
    return sent


def meeting_ended(meeting):
    """The outputs of a meeting: adopted proposals and elections, or the
    outcomes of a tactical meeting's tensions"""
    from governance.meetings.outputs import meeting_outputs

    outputs = meeting_outputs(meeting)
    if not (any(outputs.values()) or meeting.minutes):
        return 0
    users = Q(pk__in=meeting.attendees.all())
    if meeting.circle:
        users |= Q(pk__in=recipients(meeting.circle))
    return send(
        User.objects.filter(users),
        lambda: _("Outputs of the %(meeting)s") % {"meeting": meeting},
        "notifications/meeting_ended.txt",
        outputs
        | {
            "meeting": meeting,
            "url": settings.BASE_URL + meeting.get_absolute_url(),
        },
    )
