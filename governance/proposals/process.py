"""The async process of proposals, see section 3 of SPEC.md

A published proposal is adopted when every circle member consented, or by
the daily task when its deadline passed without an objection or a request
for a meeting. Objections and requests move it to the next governance
meeting, like a conflict found when adopting it at the deadline.
"""

import datetime as dt
import re

from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from django.utils.translation import gettext as _

from governance.notifications import mails
from governance.proposals.instructions import ProposalError, adopt, problems
from governance.proposals.models import Proposal, Response
from governance.roles.constitution import LEAD
from governance.roles.models import Policy, Role
from governance.roles.permissions import is_member, members, proposer_roles


def affected(proposal):
    """The existing roles and policies the instructions refer to"""
    ids = {"roles": set(), "policies": set()}
    for instruction in proposal.instructions:
        for text in [instruction["path"], instruction.get("from", "")]:
            for kind, pk in re.findall(r"/(roles|policies|circles)/(\d+)", text):
                ids["roles" if kind == "circles" else kind].add(int(pk))
    return Role.objects.filter(pk__in=ids["roles"]), Policy.objects.filter(
        pk__in=ids["policies"]
    )


def check_role(proposal):
    """The tension of one of the proposer's roles (5.3.1), still now"""
    if proposal.role is None:
        raise ProposalError([
            _("Choose the role of the proposer the tension comes from.")
        ])
    if (
        proposal.role_id == proposal.circle_id
        and Role.objects.filter(pk=proposal.circle_id, is_circle=True).exists()
    ):
        # From inside a role which became a circle meanwhile, e.g. by an
        # earlier proposal of the meeting: its holders are its Circle Leads
        proposal.circle.refresh_from_db()
        if lead := proposal.circle.roles.active().filter(core_role=LEAD).first():
            proposal.role = lead
            proposal.save(update_fields=["role"])
    roles = proposer_roles(proposal.proposer, proposal.circle)
    if not roles.filter(pk=proposal.role_id).exists():
        raise ProposalError([
            _(
                "%(user)s doesn't hold %(role)s in %(circle)s anymore: choose another role."
            )
            % {
                "user": proposal.proposer,
                "role": proposal.role,
                "circle": proposal.circle,
            }
        ])


@transaction.atomic
def publish(proposal):
    if proposal.status != Proposal.DRAFT or proposal.is_tension:
        raise ProposalError([_("Only drafts with changes can be published.")])
    # Also drafts imported from GlassFrog, which have no role
    check_role(proposal)
    if found := problems(proposal):
        raise ProposalError(found)
    now = timezone.now()
    proposal.status = Proposal.PUBLISHED
    proposal.published_at = now
    proposal.deadline = now + dt.timedelta(
        days=proposal.circle.effective_async_acceptance_days()
    )
    proposal.save()  # Also sets the roles and policies it changes
    if everybody_consented(proposal):
        # Nobody else to ask, e.g. a role's only holder adding roles inside
        try_adopting(proposal)
        return proposal
    transaction.on_commit(lambda: mails.proposal_published(proposal))
    return proposal


def current_responses(proposal):
    """Responses since the latest publication: a proposal taken back to its
    draft and published again starts over"""
    responses = proposal.responses.all()
    if proposal.published_at:
        responses = responses.filter(created_at__gte=proposal.published_at)
    return responses


def waiting_for(user):
    """Published proposals of the user's circles without their consent or
    request since the latest publication, the nearest deadline first"""
    responded = Response.objects.filter(
        proposal=OuterRef("pk"),
        user=user,
        created_at__gte=OuterRef("published_at"),
    ).exclude(kind=Response.COMMENT)
    return [
        proposal
        for proposal in Proposal.objects
        .filter(status=Proposal.PUBLISHED)
        .exclude(proposer=user)
        .exclude(Exists(responded))
        .select_related("circle", "proposer")
        .order_by("deadline", "pk")
        # Also inside a role one holds and sub-circles led from above
        if is_member(user, proposal.circle)
    ]


def response_summary(proposal):
    """What the proposal page and the API show of the responses: who
    consented, requested a meeting or didn't respond yet isn't shown, only
    counted; questions and concerns have their author, because they are
    answered and integrated with them"""
    others = set(
        members(proposal.circle)
        .exclude(pk=proposal.proposer_id)
        .values_list("pk", flat=True)
    )
    # Not those of people who left the circle since
    found = [r for r in positions(proposal).values() if r.user_id in others]
    return {
        "responses": current_responses(proposal)
        .filter(
            Q(kind=Response.COMMENT)
            # Concerns, and objections raised async before
            | Q(kind__in=[Response.MEETING, Response.OBJECTION]) & ~Q(text="")
        )
        .select_related("user"),
        "consents": sum(1 for r in found if r.kind == Response.CONSENT),
        "meeting_requests": sum(1 for r in found if r.kind == Response.MEETING),
        "others": len(others),
    }


def positions(proposal):
    """The latest consent, request or objection of every member"""
    result = {}
    for response in current_responses(proposal).exclude(kind=Response.COMMENT):
        result[response.user_id] = response
    return result


def everybody_consented(proposal):
    consented = {
        user_id
        for user_id, response in positions(proposal).items()
        if response.kind == Response.CONSENT
    }
    others = set(members(proposal.circle).values_list("pk", flat=True)) - {
        proposal.proposer_id
    }
    return others <= consented


def to_meeting(proposal):
    """Only while it's published: not one adopted meanwhile (try_adopting()
    failing because another request adopted it)"""
    if Proposal.objects.filter(pk=proposal.pk, status=Proposal.PUBLISHED).update(
        status=Proposal.IN_MEETING
    ):
        proposal.status = Proposal.IN_MEETING
        return True
    return False


@transaction.atomic
def respond(proposal, user, kind, text=""):
    """Records the response, adopts or moves the proposal if it decides"""
    # Locked, with its status in the database (two last consents at once)
    proposal.status = (
        Proposal.objects
        .select_for_update()
        .values_list("status", flat=True)
        .get(pk=proposal.pk)
    )
    if proposal.status != Proposal.PUBLISHED and kind != Response.COMMENT:
        raise ProposalError([_("The proposal isn't open for responses anymore.")])
    if kind == Response.OBJECTION:
        # Objections are tested by the facilitator, so they're raised in the
        # meeting: async, members request a meeting with their concern
        raise ProposalError([_("Request a meeting to object.")])
    if user.pk == proposal.proposer_id and kind != Response.COMMENT:
        # The proposer only answers questions
        raise ProposalError([_("You don't respond to your own proposal.")])
    response = Response.objects.create(
        proposal=proposal, user=user, kind=kind, text=text
    )
    transaction.on_commit(lambda: mails.response_given(response))
    if kind in {Response.MEETING, Response.OBJECTION}:
        to_meeting(proposal)
    elif kind == Response.CONSENT and everybody_consented(proposal):
        try_adopting(proposal)
    return response


def try_adopting(proposal):
    """Adopts the proposal, or moves it to a meeting if it conflicts now;
    not one which left the async process meanwhile (brought into a meeting,
    taken back to its draft)"""
    try:
        with transaction.atomic():
            status = (
                Proposal.objects
                .select_for_update()
                .values_list("status", flat=True)
                .get(pk=proposal.pk)
            )
            if status != Proposal.PUBLISHED:
                return False
            adopt(proposal)
    except ProposalError as exc:
        # Those who got it learn why it didn't pass async; not for those
        # imported from GlassFrog, which the nightly import sets back
        problems = exc.problems
        if to_meeting(proposal) and not proposal.decided_in_glassfrog:
            transaction.on_commit(lambda: mails.proposal_to_meeting(proposal, problems))
        return False
    return True


def back_to_draft(proposal):
    """The proposer takes a published proposal back to change it"""
    if proposal.status != Proposal.PUBLISHED:
        raise ProposalError([_("Only published proposals go back to their draft.")])
    proposal.status = Proposal.DRAFT
    proposal.published_at = proposal.deadline = None
    proposal.save(update_fields=["status", "published_at", "deadline"])
    transaction.on_commit(lambda: mails.proposal_back_to_draft(proposal))


def draft_again(proposal):
    """A new draft of a withdrawn proposal for its proposer, e.g. one the
    meeting discarded"""
    if proposal.status != Proposal.WITHDRAWN or proposal.circle.archived_on:
        raise ProposalError([_("Only withdrawn proposals are drafted again.")])
    return Proposal.objects.create(
        circle=proposal.circle,
        proposer=proposal.proposer,
        role=proposal.role,
        tension=proposal.tension,
        instructions=proposal.instructions,
        names=proposal.names,
        created_at=timezone.now(),
    )


def withdraw(proposal):
    proposal.status = Proposal.WITHDRAWN
    proposal.decided_at = timezone.now()
    proposal.save(update_fields=["status", "decided_at"])


def retract(proposal):
    """The proposer withdraws a published proposal or one waiting for a
    meeting; everybody learns where it went, also those who consented"""
    withdraw(proposal)
    transaction.on_commit(lambda: mails.proposal_retracted(proposal))


def adopt_due_proposals(now=None):
    """Adopts the published proposals whose deadline passed (daily task)"""
    due = Proposal.objects.filter(
        status=Proposal.PUBLISHED, deadline__lte=now or timezone.now()
    ).select_related("circle")
    # In the order they were published: a later one may conflict with them
    due = due.order_by("published_at", "pk")
    return [proposal for proposal in due if try_adopting(proposal)]
