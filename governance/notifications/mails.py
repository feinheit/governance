"""Mails to the subscribers of circles, see section 5 of SPEC.md"""

import re

from django.conf import settings
from django.core.mail import EmailMessage
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.translation import gettext as _, gettext_noop, override

from governance.accounts.models import User
from governance.proposals.describe import describe
from governance.roles.constitution import FACILITATOR, SECRETARY
from governance.roles.permissions import (
    acting_secretaries,
    circle_leads,
    members,
    standing_in,
)


# Into a sub-circle (any depth, 5.2) and out of one, ``Applier.move()``
MOVED_INTO = re.compile(r"/roles/(\d+)/supporting_circle/(?:roles|policies)/\d+")
MOVED_OUT_OF = re.compile(r"/circles/(\d+)/(?:roles|policies)/\d+")


def recipients(circle):
    """The circle's members, and everybody who wants to know everything"""
    return User.objects.active().filter(Q(pk__in=members(circle)) | Q(notify_all=True))


def send(users, subject, template, context):
    """One mail per user, in their language; nothing for people who left.
    ``settings.MAIL_COPIES`` get a copy, unless they received it already.
    ``subject`` is a callable, called in each recipient's language."""
    sent = []
    received = set()
    for user in users.filter(is_active=True).distinct():
        _send(user, user.email, subject, template, context)
        received.add(user.email.lower())
        sent.append(user)
    if sent:
        for address in dict.fromkeys(a.lower() for a in settings.MAIL_COPIES):
            if address not in received:
                # In the language of their account, if they have one; as
                # Cc without a To, easy to filter
                user = User.objects.filter(email__iexact=address).first()
                _send(user, address, subject, template, context, copy=sent)
    return len(sent)


def first_name(user):
    return user.full_name.split()[0] if user and user.full_name.strip() else ""


def _send(user, address, subject, template, context, *, copy=None):
    """``copy``: the recipients of the mail this is a copy of"""
    language = user.language if user else None
    with override(language or settings.LANGUAGE_CODE):
        # Greeted by the first name (copies have nobody's but say whose
        # mail they are), why they get it at the end (docs/mails.md)
        name = "" if copy else first_name(user)
        greeting = _("Hello %(name)s,") % {"name": name} if name else _("Hello,")
        if copy:
            greeting = (
                _("Copy of the mail to %(recipients)s.")
                % {"recipients": ", ".join(str(recipient) for recipient in copy)}
                + f"\n\n{greeting}"
            )
        body = render_to_string(template, context | {"user": user}).strip()
        footer = _("Why you get this mail: %(url)s") % {
            "url": f"{settings.BASE_URL}/help/mails/"
        }
        EmailMessage(
            subject=str(subject()),
            body=f"{greeting}\n\n{body}\n\n-- \n{footer}\n",
            to=[] if copy else [address],
            cc=[address] if copy else [],
        ).send()


def proposal_context(proposal):
    return {
        "proposal": proposal,
        # Called by the template, in the recipient's language
        "changes": lambda: describe(proposal.instructions, proposal.names),
        "url": settings.BASE_URL + proposal.get_absolute_url(),
    }


def everybody(proposal):
    """The recipients and the proposer, e.g. an admin who isn't a member"""
    return User.objects.filter(
        Q(pk__in=recipients(proposal.circle)) | Q(pk=proposal.proposer_id)
    )


def to_everybody(proposal, subject, template, **context):
    """A mail about the proposal to its circle and its proposer; ``subject``
    is marked with ``gettext_noop()``, translated for each recipient"""
    return send(
        everybody(proposal),
        lambda: _(subject) % {"circle": proposal.circle, "proposal": proposal},
        template,
        proposal_context(proposal) | context,
    )


def proposal_published(proposal):
    return to_everybody(
        proposal,
        gettext_noop("Proposal in %(circle)s: %(proposal)s"),
        "notifications/proposal_published.txt",
    )


def proposal_back_to_draft(proposal):
    return to_everybody(
        proposal,
        gettext_noop("Back to the draft in %(circle)s: %(proposal)s"),
        "notifications/proposal_back_to_draft.txt",
    )


def proposal_to_meeting(proposal, problems):
    """It couldn't be adopted async (e.g. a conflict with a change made
    meanwhile): it waits for a meeting"""
    return to_everybody(
        proposal,
        gettext_noop("Waiting for a meeting in %(circle)s: %(proposal)s"),
        "notifications/proposal_to_meeting.txt",
        problems=problems,
    )


def proposal_retracted(proposal):
    return to_everybody(
        proposal,
        gettext_noop("Withdrawn in %(circle)s: %(proposal)s"),
        "notifications/proposal_retracted.txt",
    )


def response_given(response):
    """Questions and comments go to the proposer, the proposer's answers to
    those who asked; requests for a meeting to the proposer and the
    circle's Secretary (or who stands in), who prepares the meeting.
    Consents stay silent, adopting sends its own mail."""
    from governance.proposals.models import Response

    proposal = response.proposal
    asking = response.user_id != proposal.proposer_id
    if response.kind == Response.COMMENT and asking:
        users = User.objects.filter(pk=proposal.proposer_id)
        subject = gettext_noop("Question or comment in %(circle)s: %(proposal)s")
    elif response.kind == Response.COMMENT:
        # Those who asked or commented, also in an earlier round (they may
        # be invested), unless they left the circle meanwhile
        users = User.objects.filter(
            pk__in=proposal.responses.filter(kind=Response.COMMENT).values("user")
        ).filter(pk__in=members(proposal.circle).values("pk"))
        subject = gettext_noop("Answer in %(circle)s: %(proposal)s")
    elif response.kind == Response.MEETING:
        users = User.objects.filter(
            Q(pk=proposal.proposer_id) | Q(pk__in=acting_secretaries(proposal.circle))
        )
        subject = gettext_noop("To discuss in a meeting in %(circle)s: %(proposal)s")
    else:
        return 0
    return send(
        users.exclude(pk=response.user_id),
        # In each recipient's language
        lambda: _(subject) % {"circle": proposal.circle, "proposal": proposal},
        "notifications/response_given.txt",
        proposal_context(proposal) | {"response": response, "asking": asking},
    )


def moved_between(proposals):
    """The Secretaries and Circle Leads of the sub-circles the proposals
    moved roles or policies into or out of: the Secretary invites them to
    meetings"""
    from governance.roles.models import Assignment, Role

    pks = {
        match[1]
        for proposal in proposals
        for instruction in proposal.instructions
        if instruction["op"] == "move"
        for match in [
            MOVED_INTO.fullmatch(instruction["path"]),
            MOVED_OUT_OF.fullmatch(instruction.get("from", "")),
        ]
        if match
    }
    circles = list(Role.objects.filter(pk__in=pks))
    secretaries = Assignment.objects.current().of_core_role(SECRETARY, circles)
    leads = [user.pk for circle in circles for user in circle_leads(circle)]
    return Q(pk__in=secretaries.values("user")) | Q(pk__in=leads)


def proposal_adopted(proposal, members_before=()):
    """``members_before``: the members when adopting began, e.g. the Role Leads
    of roles the proposal moved away; also those losing roles with it (like
    ``meeting_ended()``)"""
    return send(
        everybody(proposal)
        | User.objects.active().filter(pk__in=members_before)
        | proposal.ended_role_leads.all()
        | User.objects.filter(moved_between([proposal])),
        lambda: (
            _("Adopted in %(circle)s: %(proposal)s")
            % {"circle": proposal.circle, "proposal": proposal}
        ),
        "notifications/proposal_adopted.txt",
        proposal_context(proposal),
    )


def proposal_withdrawn(proposal, adopted=None):
    """Closing the proposal's circle or role withdrew it (``adopted``: the
    proposal doing so, if any)"""
    if proposal.proposer_id is None:
        return 0
    return send(
        User.objects.filter(pk=proposal.proposer_id),
        lambda: _("Withdrawn: %(proposal)s") % {"proposal": proposal},
        "notifications/proposal_withdrawn.txt",
        proposal_context(proposal)
        | {
            "removed": bool(proposal.circle.archived_on),
            "adopted": adopted if adopted and adopted.pk else None,
            "adopted_url": settings.BASE_URL + adopted.get_absolute_url()
            if adopted and adopted.pk
            else "",
        },
    )


def domain_policy_changed(proposal):
    """A role changed a policy for its domains: everybody affected, the
    members of its circle and all sub-circles"""
    circles = [proposal.circle, *proposal.circle.sub_circles()]
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


def roles_changed(started, ended):
    """``started`` and ``ended`` are sets of ``(user_id, role_id)``; the
    roles started with their focus"""
    from governance.roles.models import Assignment, Role

    roles = Role.objects.select_related("circle").in_bulk({
        role for _user, role in started | ended
    })
    focus = {
        (user, role): focus
        for user, role, focus in Assignment.objects
        .current()
        .filter(role__in={role for _user, role in started})
        .values_list("user", "role", "focus")
    }
    sent = 0
    for user_id in sorted({user for user, _role in started | ended}):
        changes = [
            (roles[role], True, focus.get((user, role), ""))
            for user, role in sorted(started)
            if user == user_id
        ] + [
            (roles[role], False, "") for user, role in sorted(ended) if user == user_id
        ]
        sent += send(
            User.objects.filter(pk=user_id),
            lambda changes=changes: (
                _("Your roles: %(changes)s")
                % {
                    "changes": ", ".join(
                        (
                            f"{role} ({role.circle})"
                            if holds
                            else _("no longer %(role)s")
                            % {"role": f"{role} ({role.circle})"}
                        )
                        for role, holds, _focus in changes
                    )
                }
            ),
            "notifications/roles_changed.txt",
            {"changes": changes, "base_url": settings.BASE_URL},
        )
    return sent


def focus_changed(assignment, before):
    """To the Role Lead, whose focus changed from ``before``"""
    role = assignment.role
    return send(
        User.objects.filter(pk=assignment.user_id),
        lambda: (
            _("Your focus in %(role)s: %(focus)s")
            % {
                "role": f"{role} ({role.circle})",
                "focus": assignment.focus or _("none anymore"),
            }
        ),
        "notifications/focus_changed.txt",
        {
            "assignment": assignment,
            "role": role,
            "before": before,
            "url": settings.BASE_URL + role.get_absolute_url(),
        },
    )


def members_changed(circle, joined, left):
    """To the circle's Secretaries, like GlassFrog"""
    from governance.roles.models import Assignment

    joined = list(User.objects.filter(pk__in=joined).order_by("full_name", "email"))
    left = list(User.objects.filter(pk__in=left).order_by("full_name", "email"))

    def subject():
        parts = []
        if joined:
            parts.append(
                _("%(people)s joined") % {"people": ", ".join(map(str, joined))}
            )
        if left:
            parts.append(_("%(people)s left") % {"people": ", ".join(map(str, left))})
        return _("Members of %(circle)s: %(changes)s") % {
            "circle": circle,
            "changes": "; ".join(parts),
        }

    return send(
        User.objects.filter(
            pk__in=Assignment.objects
            .current()
            .of_core_role("secretary", circle)
            .values("user")
        ),
        subject,
        "notifications/members_changed.txt",
        {
            "circle": circle,
            "joined": joined,
            "left": left,
            "url": settings.BASE_URL + circle.get_absolute_url(),
        },
    )


def elections_due(day=None):
    """The weekly reminder to the Facilitators about terms ending soon
    (5.3.5), else the Secretaries and then the Circle Leads (5.3.6)"""
    from collections import defaultdict

    from governance.meetings.elections import due_elections
    from governance.roles.models import Role

    # Per user: ``(circle, the role they get it for, the due elections)``
    by_user = defaultdict(list)
    for circle in Role.objects.active().circles():
        if not (due := due_elections([circle], day=day)):
            continue
        core_role, users = standing_in(circle, [FACILITATOR, SECRETARY], day=day)
        for user_id in users.values_list("pk", flat=True):
            by_user[user_id].append((circle, core_role, due))
    sent = 0
    for user in User.objects.active().filter(pk__in=by_user):
        sent += send(
            User.objects.filter(pk=user.pk),
            lambda: _("Elections due"),
            "notifications/elections_due.txt",
            {"circles": by_user[user.pk], "base_url": settings.BASE_URL},
        )
    return sent


def meeting_recipients(meeting, proposals):
    """The attendees, the circle's members, and for adopted proposals the
    Role Leads of the roles they changed or moved away, also when absent,
    like adopting async (members before adopting)"""
    from governance.proposals.models import Proposal
    from governance.roles.models import Assignment

    users = Q(pk__in=meeting.attendees.all())
    if meeting.circle:
        users |= Q(pk__in=recipients(meeting.circle))
    if not proposals:
        return User.objects.filter(users)
    started = timezone.localdate(meeting.started_at)
    users |= Q(
        pk__in=Assignment.objects
        .filter(role__changed_by_proposals__in=proposals)
        # Those of archived roles are the proposals' ``ended_role_leads``
        .filter(role__archived_on=None)
        .filter(Q(ends_on=None) | Q(ends_on__gte=started))
        .values("user")
    ) | Q(
        # Also roles archived with them, e.g. inside a removed circle,
        # and assignments deleted because they started the same day
        pk__in=Proposal.ended_role_leads.through.objects.filter(
            proposal__in=proposals
        ).values("user")
    )
    return User.objects.filter(users | moved_between(proposals))


def meeting_ended(meeting):
    """The outputs of a meeting: adopted proposals and elections, or the
    outcomes of a tactical meeting's tensions"""
    from governance.meetings.outputs import meeting_outputs

    outputs = meeting_outputs(meeting)
    if not (any(outputs.values()) or meeting.minutes):
        return 0
    proposals = [entry["proposal"] for entry in outputs["proposals"]]
    return send(
        meeting_recipients(meeting, proposals),
        lambda: _("Outputs of the %(meeting)s") % {"meeting": meeting},
        "notifications/meeting_ended.txt",
        outputs
        | {
            "meeting": meeting,
            "url": settings.BASE_URL + meeting.get_absolute_url(),
        },
    )
