from collections import defaultdict

from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext

from governance.accounts.models import User
from governance.history.views import ASSIGNMENT_KINDS, timeline
from governance.meetings.elections import due_elections
from governance.meetings.models import Meeting
from governance.meetings.teasers import with_teasers
from governance.proposals.models import Proposal
from governance.proposals.process import waiting_for
from governance.roles.constitution import FACILITATOR, REP, SECRETARY
from governance.roles.domain_policies import can_change_domain_policies
from governance.roles.editing import can_edit_items, can_edit_strategy
from governance.roles.models import (
    Assignment,
    ChecklistItem,
    Link,
    Metric,
    Policy,
    Role,
    by_frequency,
)
from governance.roles.permissions import (
    asks_before_starting,
    can_assign,
    can_change_settings,
    can_end_assignment,
    can_start_meeting,
    circle_leads,
    proposer_roles,
)


PENDING = [Proposal.PUBLISHED, Proposal.IN_MEETING]


def current_assignments():
    return Prefetch(
        "assignments",
        queryset=Assignment.objects.current().select_related("user"),
        to_attr="current_assignments",
    )


def mark_reps(circles):
    """Marks the holders of the circles' roles who are their Circle Reps

    The constitution makes Circle Reps members of the super-circle just
    like Circle Leads, so both hold the circle's role there.
    """
    circles = [circle for circle in circles if circle.is_circle]
    reps = defaultdict(set)
    for circle_id, user_id in (
        Assignment.objects
        .current()
        .of_core_role(REP, circles)
        .values_list("role__circle", "user")
    ):
        reps[circle_id].add(user_id)
    for circle in circles:
        for assignment in getattr(circle, "current_assignments", []):
            assignment.is_rep = assignment.user_id in reps[circle.pk]


def role_items(user, role):
    """The role's checklist items and metrics; for a circle also those of its
    roles, like GlassFrog shows them"""
    # Not the sub-circles' own items, they're on the sub-circles' pages
    roles = [
        role,
        *(role.roles.active().filter(is_circle=False) if role.is_circle else []),
    ]
    for kind, label, model in [
        ("checklist", gettext("checklist"), ChecklistItem),
        ("metrics", gettext("metric"), Metric),
    ]:
        for item in model.objects.filter(role__in=roles).select_related("role"):
            item.kind, item.kind_label = kind, label
            item.editable = can_edit_items(user, item.role, model)
            # Items of the circle's roles name their role
            item.other_role = item.role if item.role_id != role.pk else None
            yield item


def start(request):
    """The own page: roles, drafts, proposals waiting for a response,
    meetings; the organization is a link away"""
    return redirect(request.user)


def organization(request):
    anchor = Role.objects.active().circles().filter(circle=None).first()
    if anchor:
        return redirect(anchor)
    return render(request, "start.html")


def split_more(objects, shown):
    """The objects shown right away and those behind the button of
    ``_show_more.html``; "Show 1 more" would take as much space as the
    object itself"""
    objects = list(objects)
    if len(objects) > shown + 1:
        return objects[:shown], objects[shown:]
    return objects, []


def recent_history(role, count=10):
    """The newest adopted proposals and changes of the role, like the
    history page's but without the assignments (the holders card has them)"""
    proposals = role.changed_by_proposals.filter(status="adopted").select_related(
        "proposer"
    )[:count]
    changes = (
        role.changes
        .exclude(kind__in=ASSIGNMENT_KINDS)
        # Only counts, the proposals of those days say more
        .exclude(kind__endswith="-unrecorded")
        # Operational, the history page shows them on request
        .exclude(kind__regex=r"^(link|metric|checklist)-")
    )
    # Whole days, their texts are merged into one change (merge_lists())
    days = changes.order_by("-date").values_list("date", flat=True).distinct()[:count]
    changes = changes.filter(date__in=list(days)).select_related("role", "policy")
    return [
        entry for _day, entries in timeline(changes, proposals) for entry in entries
    ][:count]


def former_names(role):
    """The names the role had before, oldest first, with the day they ended"""
    names = []
    for change in role.changes.filter(kind="name").order_by("date", "pk"):
        if change.old and change.old != role.name:
            names.append((change.old, change.date))
    return names


def role_detail(request, pk):
    role = get_object_or_404(
        Role.objects.select_related("circle").prefetch_related(current_assignments()),
        pk=pk,
    )
    mark_reps([role])
    policies = list(role.policies.active().select_related("domain"))
    # Linked to in the domains, opened there (frontend/open_details.js)
    domains = with_policies(list(role.domains.all()), policies)
    context = {
        "role": role,
        "ancestors": role.ancestors(),
        "can_assign": can_assign(request.user, role),
        "can_end_assignment": can_end_assignment(request.user, role),
        "can_change_settings": can_change_settings(request.user, role),
        "can_edit_strategy": can_edit_strategy(request.user, role),
        "can_edit_metrics": can_edit_items(request.user, role, Metric),
        "can_edit_checklist": can_edit_items(request.user, role, ChecklistItem),
        "can_edit_links": can_edit_items(request.user, role, Link),
        "links": role.links.all(),
        # From a role of theirs in the circle, in a role its holders (adding
        # roles inside), like proposal_create(); admins too only then
        "can_propose": not role.archived_on
        and not role.core_role
        and proposer_roles(request.user, role).exists(),
        "accountabilities": role.accountabilities.all(),
        "domains": domains,
        "policies": policies,
        # A role's policies for its domains, without governance (1.3.2)
        "can_change_domain_policies": can_change_domain_policies(request.user, role),
        "metrics": role.metrics.all(),
        "checklist_items": role.checklistitems.all(),
        # Checklist items first, then metrics, grouped by their frequency
        "role_items": by_frequency(role_items(request.user, role)),
        # Published or in a meeting: proposals affecting the role, and its
        # own (a circle's, or a role's for its inside, 1.3.1)
        "pending": Proposal.objects
        .filter(status__in=PENDING)
        .filter(Q(roles=role) | Q(circle=role))
        .distinct()
        .select_related("proposer"),
        "history": recent_history(role),
        # GlassFrog's history has many renames without a proposal
        "former_names": former_names(role),
    }
    context["pending"], context["pending_more"] = split_more(context["pending"], 5)
    context["history"], context["history_more"] = split_more(context["history"], 5)
    if role.is_circle:
        roles = list(
            role.roles
            .active()
            .prefetch_related(current_assignments())
            .order_by("position", "name")
        )
        context["core_roles"] = [r for r in roles if r.core_role]
        # Sub-circles are roles too, the badge tells them apart
        context["roles"] = [r for r in roles if not r.core_role]
        mark_reps(context["roles"])
        context["due_elections"] = due_elections([role])
    if not role.core_role and not role.archived_on:
        # Circles, and roles whose holders break them down in their inner
        # circle (1.3.1, governance meetings only)
        # With what they were about, a circle's page lists them
        context["meetings"] = with_teasers(
            role.meetings.filter(
                Q(ended_at=None) | Q(pk__in=role.meetings.order_by("-started_at")[:3])
            ).order_by("-started_at", "-pk")[:6]
            if role.is_circle
            else role.meetings.none()
        )
        context["can_start_meeting"] = can_start_meeting(request.user, role)
        context["asks_before_starting"] = asks_before_starting(request.user, role)
        context["running_meeting"] = role.meetings.running().first()
        # A circle's page shows its meetings, a role's menu links them
        context["show_meetings"] = role.is_circle
        # Also the ad hoc tactical meetings it was invited to
        context["has_meetings"] = Meeting.objects.of_role(role).exists()
    if not role.is_circle:
        context["has_proposals_inside"] = (
            Proposal.objects.visible_to(request.user).filter(circle=role).exists()
        )
    if role.circle_id:
        # Who covers the role while nobody holds it (1.4.2)
        context["leads"] = circle_leads(role.circle).order_by("full_name", "email")
    return render(request, "roles/role_detail.html", context)


def with_policies(domains, policies):
    """The domains with their policies (``role_policies``)"""
    for domain in domains:
        domain.role_policies = [p for p in policies if p.domain_id == domain.pk]
    return domains


def role_context(request, pk):
    """What constrains the role from outside: per circle containing it, from
    the outermost down, the circle's domains and policies (5.2.1) and the
    domains of its roles with their policies (1.3.2); the role's page opens
    it in a modal"""
    role = get_object_or_404(Role.objects.select_related("circle"), pk=pk)
    ancestors = role.ancestors()
    circles = []
    for circle, inner in zip(ancestors, [*ancestors[1:], role], strict=True):
        policies = list(circle.policies.active().select_related("domain"))
        roles = []
        # Not the circle on the way down, it follows with its own section,
        # nor the role itself
        for other in (
            circle.roles
            .active()
            .exclude(pk=inner.pk)
            .prefetch_related(
                "domains", Prefetch("policies", queryset=Policy.objects.active())
            )
            .order_by("position", "name")
        ):
            domains = list(other.domains.all())
            core_domains = other.core.domains if other.core else []
            if domains or core_domains:
                roles.append({
                    "role": other,
                    "core_domains": core_domains,
                    "domains": with_policies(domains, list(other.policies.all())),
                })
        circles.append({
            "circle": circle,
            "domains": with_policies(list(circle.domains.all()), policies),
            "policies": [p for p in policies if not p.domain_id],
            "roles": roles,
        })
    return render(
        request,
        "roles/role_context.html",
        {
            "role": role,
            "title": gettext("Domains and policies affecting this circle")
            if role.is_circle
            else gettext("Domains and policies affecting this role"),
            "circles": circles,
        },
    )


def policy_detail(request, pk):
    policy = get_object_or_404(Policy.objects.select_related("role", "domain"), pk=pk)
    # Its changes and the adopted proposals changing it, few: all of them
    history = [
        entry
        for _day, entries in timeline(
            policy.changes.select_related("role", "policy"),
            policy.changed_by_proposals.filter(status="adopted").select_related(
                "circle", "proposer"
            ),
        )
        for entry in entries
    ]
    history, history_more = split_more(history, 5)
    return render(
        request,
        "roles/policy_detail.html",
        {
            "policy": policy,
            "ancestors": [*policy.role.ancestors(), policy.role],
            "history": history,
            "history_more": history_more,
            "pending": policy.changed_by_proposals.filter(
                status__in=PENDING
            ).select_related("proposer"),
        },
    )


def people(request):
    users = (
        User.objects
        .active()
        .filter(
            assignments__in=Assignment.objects.current().filter(role__archived_on=None)
        )
        .distinct()
    )
    return render(request, "roles/people.html", {"users": users})


def person_detail(request, pk):
    user = get_object_or_404(User, pk=pk)
    assignments = (
        Assignment.objects
        .current()
        .filter(user=user, role__archived_on=None)
        .select_related("role__circle")
        .order_by("role__circle__name", "role__position", "role__name")
    )
    by_circle = defaultdict(list)
    for assignment in assignments:
        by_circle[assignment.role.circle].append(assignment)
    # Circles in depth-first order, like the organization's structure
    order = {
        circle.pk: index for index, circle in enumerate(Role.objects.depth_first())
    }
    by_circle = dict(
        sorted(
            by_circle.items(),
            key=lambda item: order.get(item[0].pk if item[0] else None, -1),
        )
    )
    past = (
        Assignment.objects
        .filter(user=user, ends_on__isnull=False)
        .select_related("role__circle")
        .order_by("-ends_on")
    )
    past, past_more = split_more(past, 5)
    context = {
        "person": user,
        "by_circle": by_circle,
        "past": past,
        "past_more": past_more,
    }
    if user == request.user:
        # Facilitators (who trigger them, 5.3.5) and Secretaries see the
        # elections due in their circles
        context["due_elections"] = due_elections([
            assignment.role.circle
            for assignment in assignments
            if assignment.role.core_role in {FACILITATOR, SECRETARY}
        ])
        context |= {
            # Ad-hoc tactical meetings have no circle page
            "meetings": Meeting.objects
            .filter(attendees=user, ended_at=None)
            .select_related("circle")
            .order_by("started_at", "pk"),
            "drafts": Proposal.objects
            .filter(proposer=user, status=Proposal.DRAFT)
            .select_related("circle")
            .order_by("-created_at"),
            "waiting": waiting_for(user),
        }
        context["drafts"], context["drafts_more"] = split_more(context["drafts"], 5)
        context["waiting"], context["waiting_more"] = split_more(context["waiting"], 5)
    return render(request, "roles/person_detail.html", context)
