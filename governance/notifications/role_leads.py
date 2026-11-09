"""Mails about changing Role Leads: the people about the roles they get and
lose, the circles' Secretaries about people joining and leaving; see section
5 of SPEC.md"""

from contextlib import contextmanager
from functools import partial

from django.db import transaction

from governance.notifications import mails
from governance.roles.models import Assignment
from governance.roles.permissions import members


@contextmanager
def announce(circles):
    """Mails about the assignments changing inside the block (like
    GlassFrog): the people about the roles they get and lose, the circles'
    Secretaries about people joining and leaving. A circle's role in the
    super-circle follows its Circle Leads and Rep, it isn't announced."""
    circles = {circle for circle in circles if circle is not None}
    before = role_leads_and_members(circles)
    # Nothing to announce when the block fails
    yield  # noqa: RUF075
    announce_changes(circles, before, role_leads_and_members(circles))


def role_leads_and_members(circles):
    """``(role_leads, members)``: the Role Leads of the circles' roles as
    ``(user, role)``, and the circles' members"""
    role_leads = set(
        Assignment.objects
        .current()
        .filter(role__circle__in=circles, role__is_circle=False)
        .values_list("user", "role")
    )
    # Also people deactivated meanwhile, members() only has active ones
    joined = {
        circle: set(members(circle).values_list("pk", flat=True))
        | set(
            Assignment.objects
            .current()
            .filter(role__circle=circle)
            .values_list("user", flat=True)
        )
        for circle in circles
    }
    return role_leads, joined


def announce_changes(circles, before, after):
    """Mails the differences of two ``role_leads_and_members()``, after
    committing"""
    (role_leads, joined), (now_role_leads, now_joined) = before, after
    started, ended = now_role_leads - role_leads, role_leads - now_role_leads
    changes = [
        (
            circle,
            now_joined[circle] - joined[circle],
            joined[circle] - now_joined[circle],
        )
        for circle in circles
        if now_joined[circle] != joined[circle]
    ]
    if started or ended:
        transaction.on_commit(partial(mails.roles_changed, started, ended))
    for circle, new, gone in changes:
        transaction.on_commit(partial(mails.members_changed, circle, new, gone))
