from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.formats import date_format
from django.utils.translation import gettext, gettext_lazy as _
from django.views.decorators.http import require_POST

from governance.filters import FilterForm, RoleField
from governance.forms import Form
from governance.proposals import process
from governance.proposals.describe import describe
from governance.proposals.drafting import can_edit
from governance.proposals.instructions import ProposalError, consequences, problems
from governance.proposals.models import Proposal, Response
from governance.roles.models import Policy, Role
from governance.roles.permissions import is_member, members as circle_members


class ResponseForm(Form):
    kind = forms.ChoiceField(
        label=_("Response"),
        choices=[c for c in Response.KIND_CHOICES if c[0] != Response.OBJECTION],
        widget=forms.RadioSelect,
    )
    text = forms.CharField(
        label=_("Text"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text=_(
            "Required for questions. If you want to discuss the proposal in a"
            " meeting, you can give your reasons here, but you don't have to."
        ),
    )

    def __init__(self, *args, is_open, is_proposer=False, **kwargs):
        super().__init__(*args, **kwargs)
        # In a meeting, and for the proposer: only questions and comments
        if not is_open or is_proposer:
            self.fields["kind"].choices = Response.KIND_CHOICES[:1]
            self.fields["kind"].initial = Response.COMMENT

    def clean(self):
        data = super().clean()
        data["text"] = data.get("text", "").strip()
        if data.get("kind") == Response.COMMENT and not data["text"]:
            self.add_error("text", _("Please explain."))
        if data.get("kind") == Response.CONSENT and data["text"]:
            # Consents are only counted: refused instead of dropped
            self.add_error(
                "text",
                _("No objection takes no text: ask a question or request a meeting."),
            )
        return data


def links(proposal, changes):
    """URLs of the roles and policies a proposal's changes belong to"""
    # Objects added by a draft have keys like n1 instead of IDs
    keys = {
        change.subject_key
        for change in changes
        if change.subject_key and change.subject_key.split("/")[1].isdigit()
    }
    ids = {
        kind: {int(key.split("/")[1]) for key in keys if key.startswith(f"{kind}/")}
        for kind in ["roles", "policies"]
    }
    # Proposals adopted in GlassFrog refer to GlassFrog IDs, open ones were
    # converted to the app's IDs like the app's own (import, to_app_ids()).
    # Those adopted here have a role, the import sets none.
    imported = (
        proposal.glassfrog_id
        and proposal.status == Proposal.ADOPTED
        and proposal.role_id is None
    )
    field = "glassfrog_id" if imported else "pk"
    urls = {}
    for kind, model in [("roles", Role), ("policies", Policy)]:
        for obj in model.objects.filter(**{f"{field}__in": ids[kind]}):
            urls[f"{kind}/{getattr(obj, field)}"] = obj.get_absolute_url()
    return urls


class ProposalFilters(FilterForm):
    status = forms.ChoiceField(
        label=_("Status"),
        choices=[("", _("All statuses")), *Proposal.STATUS_CHOICES],
        required=False,
    )
    # Where it's decided: a circle, or a role for its inside (1.3.1)
    circle = RoleField(label=_("Circle"), empty_label=_("All circles"))
    sub_circles = forms.BooleanField(label=_("With sub-circles"), required=False)
    role = RoleField(label=_("Changing"), empty_label=_("Changing any role"))


def proposal_list(request):
    filters = ProposalFilters(request.GET)
    proposals = Proposal.objects.visible_to(request.user).select_related(
        "circle", "proposer"
    )
    if circle_id := filters.get("circle"):
        circle = get_object_or_404(Role, pk=circle_id)
        circles = [
            circle,
            *(circle.sub_circles() if filters.get("sub_circles") else []),
        ]
        proposals = proposals.filter(circle__in=circles)
    if role_id := filters.get("role"):
        proposals = proposals.filter(roles=role_id)
    if status := filters.get("status"):
        proposals = proposals.filter(status=status)
    page = Paginator(proposals.distinct(), 50).get_page(request.GET.get("page"))
    return render(
        request,
        "proposals/proposal_list.html",
        {"page": page, "filters": filters},
    )


def annotate_changes(proposal):
    """The readable changes with what the draft's controls need"""
    changes = describe(proposal.instructions, proposal.names)
    urls = links(proposal, changes)
    seen = set()
    removed = {
        i["path"].lstrip("/") for i in proposal.instructions if i["op"] == "remove"
    }
    for change in changes:
        # Removed or moved elsewhere: nothing to edit in this circle
        change.is_editable = (
            change.subject_key not in removed and change.action != "moved"
        )
        change.url = urls.get(change.subject_key)
        # The draft's actions on the first change of each role or policy
        change.first_of_subject = change.subject_key not in seen
        seen.add(change.subject_key)
        if change.subject_key:
            change.kind, change.key = change.subject_key.split("/")
    return changes


def drafting_context(proposal):
    """What the controls changing a draft (or amending it in a meeting) need"""
    circle = proposal.circle
    return {
        "editable": True,
        "problems": problems(proposal) if proposal.instructions else [],
        # E.g. circles losing their last roles turn back into roles
        "consequences": consequences(proposal) if proposal.instructions else {},
        # The anchor circle changes its own purpose and accountabilities
        "circle_roles": ([] if circle.circle_id else [circle])
        # The core roles stay as the constitution defines them
        + list(circle.roles.active().filter(core_role="").order_by("position", "name")),
        # Its roles change their policies for their domains themselves (1.3.2),
        # also a role adding roles inside it
        "circle_policies": Policy.objects.active().filter(
            role=circle, role__is_circle=True
        ),
    }


def proposal_detail(request, pk):
    proposal = get_object_or_404(
        Proposal.objects.visible_to(request.user).select_related(
            "circle", "proposer", "meeting"
        ),
        pk=pk,
    )
    context = {"proposal": proposal, "changes": annotate_changes(proposal)}
    meeting = proposal.meeting
    if proposal.status == Proposal.IN_MEETING and meeting and meeting.is_running:
        # The secretary amends it in the meeting, the others see it there
        context["amended_in"] = meeting
    elif can_edit(request.user, proposal):
        context |= drafting_context(proposal)
    elif proposal.status in {Proposal.PUBLISHED, Proposal.IN_MEETING}:
        # Those responding see what adopting it does automatically
        context["consequences"] = consequences(proposal)
    if proposal.status in {Proposal.PUBLISHED, Proposal.IN_MEETING}:
        members = circle_members(proposal.circle)
        context |= {"show_responses": True} | process.response_summary(proposal)
        # Circle members only, also no admins outside it (5.3)
        if members.filter(pk=request.user.pk).exists():
            context["response_form"] = ResponseForm(
                is_open=proposal.status == Proposal.PUBLISHED,
                is_proposer=proposal.proposer_id == request.user.pk,
            )
        context["can_withdraw"] = (
            proposal.proposer_id == request.user.pk and "amended_in" not in context
        )
    context["can_draft_again"] = (
        proposal.status == Proposal.WITHDRAWN
        and proposal.proposer_id == request.user.pk
        and not proposal.circle.archived_on
    )
    return render(request, "proposals/proposal_detail.html", context)


def own_proposal(request, pk, statuses):
    proposal = get_object_or_404(
        Proposal.objects.visible_to(request.user), pk=pk, status__in=statuses
    )
    if proposal.proposer != request.user:
        raise PermissionDenied
    return proposal


@require_POST
def proposal_publish(request, pk):
    proposal = own_proposal(request, pk, [Proposal.DRAFT])
    try:
        process.publish(proposal)
    except ProposalError as exc:
        for problem in exc.problems:
            messages.error(request, problem)
    else:
        messages.success(
            request,
            gettext(
                "The proposal has been published. It is adopted on %(date)s unless"
                " somebody requests a meeting to discuss it."
            )
            % {"date": date_format(proposal.adopted_on, "SHORT_DATE_FORMAT")},
        )
    return redirect(proposal)


@require_POST
def proposal_back_to_draft(request, pk):
    proposal = own_proposal(request, pk, [Proposal.PUBLISHED])
    process.back_to_draft(proposal)
    messages.success(
        request,
        gettext(
            "The proposal is a draft again. Publish it again when it's ready,"
            " the circle starts over then."
        ),
    )
    return redirect(proposal)


@require_POST
def proposal_draft_again(request, pk):
    proposal = own_proposal(request, pk, [Proposal.WITHDRAWN])
    try:
        draft = process.draft_again(proposal)
    except ProposalError as exc:
        for problem in exc.problems:
            messages.error(request, problem)
        return redirect(proposal)
    return redirect(draft)


def proposal_withdraw(request, pk):
    """Withdrawing a proposal, confirmed first (in a modal on its page)"""
    proposal = own_proposal(request, pk, [Proposal.PUBLISHED, Proposal.IN_MEETING])
    if proposal.meeting and proposal.meeting.is_running:
        # The secretary discards it there (5.3.1)
        raise PermissionDenied
    if request.method != "POST":
        return render(
            request,
            "generic/confirm.html",
            {
                "question": gettext("Withdraw %(proposal)s?") % {"proposal": proposal},
                "help": gettext(
                    "The circle doesn't decide it anymore. You can draft it again"
                    " afterwards."
                ),
                "submit_label": gettext("Withdraw"),
                "cancel_url": proposal.get_absolute_url(),
            },
        )
    process.retract(proposal)
    messages.success(request, gettext("The proposal has been withdrawn."))
    return redirect(proposal)


@require_POST
def proposal_respond(request, pk):
    proposal = get_object_or_404(Proposal.objects.exclude(status=Proposal.DRAFT), pk=pk)
    if not is_member(request.user, proposal.circle):
        raise PermissionDenied
    if proposal.status not in {Proposal.PUBLISHED, Proposal.IN_MEETING}:
        # Adopted or withdrawn while the page was open
        messages.error(
            request, gettext("The proposal isn't open for responses anymore.")
        )
        return redirect(proposal)
    form = ResponseForm(
        request.POST,
        is_open=proposal.status == Proposal.PUBLISHED,
        is_proposer=proposal.proposer_id == request.user.pk,
    )
    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect(proposal)
    try:
        process.respond(
            proposal, request.user, form.cleaned_data["kind"], form.cleaned_data["text"]
        )
    except ProposalError as exc:  # E.g. decided by another request meanwhile
        for problem in exc.problems:
            messages.error(request, problem)
        return redirect(proposal)
    proposal.refresh_from_db()
    if proposal.status == Proposal.ADOPTED:
        messages.success(
            request, gettext("Everybody consented, the proposal is adopted.")
        )
    elif proposal.status == Proposal.IN_MEETING:
        messages.info(
            request, gettext("The proposal goes to the next governance meeting.")
        )
    return redirect(proposal)
