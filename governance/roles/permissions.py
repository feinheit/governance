"""Who may do what outside the governance process, see section 3 of SPEC.md

Circle Leads assign people to the roles of their circle (and the Circle
Lead of a sub-circle). Admins may do it everywhere, e.g. assign the anchor
circle's Circle Lead. Everything else changes through governance, also
spelling.

The checks return why somebody may do something, empty when they may not:
``ALLOWED`` (through their roles, the constitution or the app's own rules),
``AS_SECRETARY`` (the Secretary standing in for the Circle Leads, which the
constitution doesn't do) or ``AS_ADMIN``. The pages mark the latter two
(``generic/_right.html``, the ``elevated`` filter).
"""

from django.db.models import Q

from governance.roles.constitution import FACILITATOR, LEAD, REP, SECRETARY
from governance.roles.models import Assignment, Role


NOT_ALLOWED = ""
ALLOWED = "allowed"
AS_SECRETARY = "secretary"
AS_ADMIN = "admin"


def as_admin(user):
    return AS_ADMIN if user.is_admin else NOT_ALLOWED


def holds_core_role(user, circle, core_role):
    return (
        circle is not None
        and Assignment.objects
        .current()
        .of_core_role(core_role, circle)
        .filter(user=user)
        .exists()
    )


def circle_leads(circle):
    """The circle's Circle Leads: the Role Leads of its Circle Lead role, while
    nobody holds it those of the super-circle (1.4.2: its Circle Leads lead
    the unfilled role, and so its inner circle), recursively. The anchor
    circle has none unless assigned (1.4). A role's inner circle is led by
    those filling the role (1.4). Archived circles have none."""
    from governance.accounts.models import User

    if circle is not None and circle.archived_on:
        return User.objects.none()
    if circle is not None and not circle.is_circle:
        return role_leads(circle)
    while circle is not None:
        leads = User.objects.active().filter(
            pk__in=Assignment.objects
            .current()
            .of_core_role(LEAD, circle)
            .values("user")
        )
        if circle.circle_id is None or leads.exists():
            return leads
        circle = circle.circle
    return User.objects.none()


def role_leads(role):
    """Who fills a role: its Role Leads, while nobody holds it its circle's
    Circle Leads (1.4.2), except an unfilled Circle Rep, which is nobody's;
    archived roles have none"""
    from governance.accounts.models import User

    if role.archived_on:
        return User.objects.none()
    role_leads = User.objects.active().filter(
        pk__in=Assignment.objects.current().filter(role=role).values("user")
    )
    if role_leads.exists() or role.circle is None or role.core_role == REP:
        return role_leads
    return circle_leads(role.circle)


def stand_ins(circle, core_roles, *, day=None):
    """The Role Leads of the first of the circle's core roles somebody holds,
    else its Circle Leads: who stands in for unfilled roles, in the order
    given (constitution 5.3.6)"""
    from governance.accounts.models import User

    for core_role in core_roles:
        users = User.objects.active().filter(
            pk__in=Assignment.objects
            .current(on=day)
            .of_core_role(core_role, circle)
            .values("user")
        )
        if users.exists():
            return users
    return circle_leads(circle)


def acting_secretaries(circle):
    """Who acts as the circle's Secretary: its Secretary, else its
    Facilitator, else its Circle Leads (constitution 5.3.6)"""
    return stand_ins(circle, [SECRETARY, FACILITATOR])


def is_circle_lead(user, circle):
    return circle is not None and circle_leads(circle).filter(pk=user.pk).exists()


def can_lead(user, circle):
    """What the circle's Circle Leads may do in the app

    The Secretary stands in, although the constitution doesn't give them
    these rights.
    """
    if circle is None:
        return NOT_ALLOWED
    if is_circle_lead(user, circle):
        return ALLOWED
    if holds_core_role(user, circle, SECRETARY):
        return AS_SECRETARY
    return as_admin(user)


def can_end_assignment(user, role):
    """Circle Leads end assignments of their circle's roles, also of elected
    roles: their Role Leads resign through them (1.4.1). The super-circle's
    Circle Leads do it for a sub-circle's Circle Lead."""
    if role.archived_on or role.is_circle or not role.circle:
        return NOT_ALLOWED
    circle = role.circle.circle if role.core_role == LEAD else role.circle
    return can_lead(user, circle) or as_admin(user)


def can_assign(user, role):
    """Those who end assignments also assign, except to elected roles"""
    if role.is_elected:
        return NOT_ALLOWED
    return can_end_assignment(user, role)


def members(circle):
    """Members of a circle hold one of its roles (also of its sub-circles,
    whose Circle Leads and Circle Reps hold the sub-circle's role), and its
    Circle Leads (also those of the super-circle standing in)"""
    from governance.accounts.models import User

    if not circle.is_circle:
        # A role's inner circle, before it has roles (constitution 1.3.1):
        # its Role Leads, while nobody holds it its circle's Circle Leads (1.4.2)
        return role_leads(circle)
    return User.objects.active().filter(
        Q(
            pk__in=Assignment.objects
            .current()
            .filter(role__circle=circle, role__archived_on=None)
            .values("user")
        )
        | Q(pk__in=circle_leads(circle).values("pk"))
    )


def is_member(user, circle):
    return members(circle).filter(pk=user.pk).exists()


def proposer_roles(user, circle):
    """The roles a person may propose from in a circle

    A proposal addresses a tension of one of the proposer's roles
    (constitution 5.3.1): the roles they hold in the circle (also the roles
    of sub-circles, held by their Circle Leads and Circle Reps), and as
    Circle Lead also the roles nobody holds (1.4.2), except the Circle Rep:
    the Circle Lead isn't eligible for it.
    """
    if not circle.is_circle:
        # Adding roles inside the role: its Role Leads (or Circle Leads), for
        # the role itself
        if not role_leads(circle).filter(pk=user.pk).exists():
            return Role.objects.none()
        return Role.objects.active().filter(pk=circle.pk)
    roles = Role.objects.active().filter(circle=circle)
    held = Assignment.objects.current().filter(user=user).values("role")
    condition = Q(pk__in=held)
    if is_circle_lead(user, circle):
        condition |= ~Q(pk__in=Assignment.objects.current().values("role")) & ~Q(
            core_role=REP
        )
    return roles.filter(condition).order_by("position", "name")


def can_start_meeting(user, circle):
    """Who starts and runs the circle's meetings

    Usually the Facilitator and the Secretary, but anybody may stand in for
    them: the other one of them, the Circle Lead, and finally the first
    circle member who declares to stand in (constitution 5.3.6). Not in
    archived circles.
    """
    if circle.archived_on:
        return NOT_ALLOWED
    if is_member(user, circle):
        return ALLOWED
    return as_admin(user)


def asks_before_starting(user, circle):
    """Starting a meeting asks first: in a role (its own governance, rarely
    what people want, 1.3.1), and in a circle for somebody who isn't its
    Secretary or standing in for them: the Secretary schedules them"""
    if not circle.is_circle:
        return True
    return not acting_secretaries(circle).filter(pk=user.pk).exists()


def can_change_settings(user, role):
    """The Secretary changes a circle's settings (acceptance period) and
    whether a policy makes a role of the circle elected"""
    if role.archived_on or role.core_role:
        return NOT_ALLOWED
    if holds_core_role(user, role.governing_circle, SECRETARY):
        return ALLOWED
    return as_admin(user)
