from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.formats import date_format
from django.utils.translation import gettext, gettext_lazy as _
from django.views.decorators.http import require_POST

from governance.forms import Form
from governance.proposals import process
from governance.proposals.describe import describe
from governance.proposals.drafting import can_edit
from governance.proposals.instructions import ProposalError, consequences, problems
from governance.proposals.models import Proposal, Response
from governance.roles.constitution import LEAD
from governance.roles.models import Policy, Role
from governance.roles.permissions import is_member, members as circle_members


class ResponseForm(Form):
    kind = forms.ChoiceField(
        label=_("Response"),
        choices=[c for c in Response.KIND_CHOICES if c[0] != Response.OBJECTION],
        widget=forms.RadioSelect,
        initial=Response.CONSENT,
    )
    text = forms.CharField(
        label=_("Text"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text=_(
            "Required for questions. When requesting a meeting: the concern to"
            " discuss, optional."
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
    # Imported proposals refer to GlassFrog IDs, the app's own to its IDs
    field = "glassfrog_id" if proposal.glassfrog_id else "pk"
    urls = {}
    for kind, model in [("roles", Role), ("policies", Policy)]:
        for obj in model.objects.filter(**{f"{field}__in": ids[kind]}):
            urls[f"{kind}/{getattr(obj, field)}"] = obj.get_absolute_url()
    return urls


def proposal_list(request):
    proposals = Proposal.objects.visible_to(request.user).select_related(
        "circle", "proposer"
    )
    circle = None
    if circle_id := request.GET.get("circle"):
        circle = get_object_or_404(Role, pk=circle_id)
        proposals = proposals.filter(circle=circle)
    role = None
    if role_id := request.GET.get("role"):
        role = get_object_or_404(Role, pk=role_id)
        proposals = proposals.filter(roles=role)
    if status := request.GET.get("status"):
        proposals = proposals.filter(status=status)
    page = Paginator(proposals, 50).get_page(request.GET.get("page"))
    return render(
        request,
        "proposals/proposal_list.html",
        {
            "page": page,
            "circle": circle,
            "role": role,
            "status": status,
            "status_choices": Proposal.STATUS_CHOICES,
        },
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
        # Circles losing their last roles turn back into roles
        "reverting": consequences(proposal) if proposal.instructions else [],
        # The anchor circle changes its own purpose and accountabilities
        "circle_roles": ([] if circle.circle_id else [circle])
        # The Circle Lead stays as the constitution defines it
        + list(
            circle.roles.active().exclude(core_role=LEAD).order_by("position", "name")
        ),
        "circle_policies": Policy.objects.active().filter(
            Q(role=circle) | Q(role__circle=circle)
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
    if can_edit(request.user, proposal):
        context |= drafting_context(proposal)
    if proposal.status in {Proposal.PUBLISHED, Proposal.IN_MEETING}:
        members = circle_members(proposal.circle)
        positions = process.positions(proposal).values()
        context |= {
            "show_responses": True,
            # Who consented, requested a meeting or didn't respond yet isn't
            # shown: questions and objections have their author, because
            # they are answered and integrated with them
            "responses": process
            .current_responses(proposal)
            .filter(
                Q(kind=Response.COMMENT)
                # Concerns, and objections raised async before
                | Q(kind__in=[Response.MEETING, Response.OBJECTION]) & ~Q(text="")
            )
            .select_related("user"),
            "consents": sum(1 for r in positions if r.kind == Response.CONSENT),
            "meeting_requests": sum(1 for r in positions if r.kind == Response.MEETING),
            "others": members.exclude(pk=proposal.proposer_id).count(),
        }
        if request.user.is_admin or members.filter(pk=request.user.pk).exists():
            context["response_form"] = ResponseForm(
                is_open=proposal.status == Proposal.PUBLISHED,
                is_proposer=proposal.proposer_id == request.user.pk,
            )
        context["can_withdraw"] = proposal.proposer_id == request.user.pk
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
def proposal_withdraw(request, pk):
    proposal = own_proposal(request, pk, [Proposal.PUBLISHED, Proposal.IN_MEETING])
    process.withdraw(proposal)
    messages.success(request, gettext("The proposal has been withdrawn."))
    return redirect(proposal)


@require_POST
def proposal_respond(request, pk):
    proposal = get_object_or_404(
        Proposal.objects.filter(status__in=[Proposal.PUBLISHED, Proposal.IN_MEETING]),
        pk=pk,
    )
    if not (request.user.is_admin or is_member(request.user, proposal.circle)):
        raise PermissionDenied
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
    process.respond(
        proposal, request.user, form.cleaned_data["kind"], form.cleaned_data["text"]
    )
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
