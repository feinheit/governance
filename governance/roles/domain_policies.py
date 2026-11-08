"""Policies of a role for its domains, changed by the role, not governance

A role controlling a domain may issue policies regulating it within its own
governance (constitution 1.3.2), e.g. who may access a server. The role's
holders add, change and remove them directly, and the Circle Lead while
nobody holds the role (1.4.2). Each change is recorded as an adopted
proposal of its own kind, so that the history shows it with its diff, and
mailed to everybody affected: the members of the role's circle and its
sub-circles, and everybody who wants to know everything.
"""

from django import forms
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext

from governance.forms import ModelForm
from governance.history.update import update_today
from governance.proposals.models import Proposal
from governance.roles.models import Assignment, Domain, Policy, Role
from governance.roles.permissions import (
    ALLOWED,
    NOT_ALLOWED,
    as_admin,
    can_lead,
)


def can_change_domain_policies(user, role):
    """Its holders, while nobody holds it its Circle Leads (1.4.2)"""
    if role.archived_on or role.is_circle or role.core_role:
        return NOT_ALLOWED
    if not role.domains.exists():
        return NOT_ALLOWED
    holders = Assignment.objects.current().filter(role=role)
    if holders.filter(user=user).exists():
        return ALLOWED
    return (not holders.exists() and can_lead(user, role.circle)) or as_admin(user)


class DomainPolicyForm(ModelForm):
    class Meta:
        model = Policy
        fields = ["title", "body", "domain"]
        widgets = {"body": forms.Textarea(attrs={"rows": 8, "data-mentions": True})}

    def __init__(self, *args, role, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["domain"].queryset = Domain.objects.filter(role=role)
        self.fields["domain"].required = True
        self.fields["domain"].empty_label = None


def record(user, role, policy, instructions):
    """The change as an adopted proposal, mailed when committed"""
    from governance.notifications.mails import domain_policy_changed

    now = timezone.now()
    proposal = Proposal.objects.create(
        circle=role.circle,
        proposer=user,
        role=role,
        status=Proposal.ADOPTED,
        created_at=now,
        decided_at=now,
        instructions=instructions,
        names={
            f"policies/{policy.pk}": policy.title,
            f"roles/{role.pk}": role.name,
            **(
                {f"domains/{policy.domain_id}": str(policy.domain)}
                if policy.domain
                else {}
            ),
        },
    )
    proposal.roles.add(role)
    proposal.policies.add(policy)
    transaction.on_commit(lambda: domain_policy_changed(proposal))
    update_today()
    return proposal


def changes(policy, old, new):
    """``replace`` instructions with the old values, like in proposals"""
    path = f"/policies/{policy.pk}"
    result = [
        {
            "op": "replace",
            "path": f"{path}/{field}",
            "original_value": old[field],
            "value": new[field],
        }
        for field in ["title", "body"]
        if old[field] != new[field]
    ]
    if old["domain"] != new["domain"]:
        result.append({
            "op": "replace",
            "path": f"{path}/links/domain",
            "original_value": str(old["domain"] or ""),
            "value": str(new["domain"] or ""),
        })
    return result


@transaction.atomic
def domain_policy_edit(request, pk, policy_pk=None):
    role = get_object_or_404(Role, pk=pk)
    if not (right := can_change_domain_policies(request.user, role)):
        raise PermissionDenied
    policy = (
        get_object_or_404(Policy.objects.active(), pk=policy_pk, role=role)
        if policy_pk
        else None
    )
    old = {
        "title": policy.title if policy else "",
        "body": policy.body if policy else "",
        "domain": policy.domain_id if policy else None,
    }
    form = DomainPolicyForm(
        request.POST or None,
        instance=policy,
        role=role,
        # Added from the domain's line on the role's page
        initial=None if policy else {"domain": request.GET.get("domain")},
    )
    if form.is_valid():
        is_new = policy is None
        policy = form.save(commit=False)
        policy.role = role
        policy.save()
        new = {"title": policy.title, "body": policy.body, "domain": policy.domain_id}
        if is_new:
            path = f"/policies/{policy.pk}"
            instructions = [
                {"op": "add", "path": path},
                {"op": "add", "path": f"{path}/title", "value": policy.title},
                {"op": "add", "path": f"{path}/body", "value": policy.body},
                {
                    "op": "add",
                    "path": f"{path}/links/domain",
                    "value": str(policy.domain_id),
                },
            ]
        else:
            instructions = changes(policy, old, new)
        if instructions:
            record(request.user, role, policy, instructions)
        return redirect(role)
    return render(
        request,
        "generic/object_form.html",
        {
            "title": gettext("Change %(policy)s") % {"policy": policy}
            if policy
            else gettext("New policy of %(role)s") % {"role": role},
            "help": gettext(
                "The role regulates its domains with its own policies, without a"
                " governance process (constitution 1.3.2). Everybody in %(circle)s"
                " and its sub-circles is informed."
            )
            % {"circle": role.circle},
            "form": form,
            "right": right,
            "cancel_url": role.get_absolute_url(),
        },
    )


@transaction.atomic
def domain_policy_remove(request, pk, policy_pk):
    """Removing a policy, confirmed first (in a modal on the role's page)"""
    role = get_object_or_404(Role, pk=pk)
    if not (right := can_change_domain_policies(request.user, role)):
        raise PermissionDenied
    policy = get_object_or_404(Policy.objects.active(), pk=policy_pk, role=role)
    if request.method != "POST":
        return render(
            request,
            "generic/confirm.html",
            {
                "question": gettext("Remove the policy %(policy)s?")
                % {"policy": policy},
                "help": gettext(
                    "Everybody in %(circle)s and its sub-circles is informed."
                )
                % {"circle": role.circle},
                "submit_label": gettext("Remove"),
                "right": right,
                "cancel_url": role.get_absolute_url(),
            },
        )
    policy.archived_on = timezone.localdate()
    policy.save(update_fields=["archived_on"])
    record(
        request.user, role, policy, [{"op": "remove", "path": f"/policies/{policy.pk}"}]
    )
    return redirect(role)
