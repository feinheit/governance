import datetime as dt

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import Truncator
from django.utils.translation import gettext_lazy as _


# When the daily task (``fairy_tasks``) adopts due proposals, see the cron
# jobs in argocd's governance/values.yaml
NIGHTLY_RUN = dt.time(3, 30)


class ProposalQuerySet(models.QuerySet):
    def visible_to(self, user):
        """Drafts (also tensions) are private to their proposer"""
        return self.filter(~models.Q(status=Proposal.DRAFT) | models.Q(proposer=user))


class Proposal(models.Model):
    """A proposed change of a circle's governance

    ``instructions`` use GlassFrog's JSON-patch-like format (``add``,
    ``replace``, ``remove``, ``move``, ``test`` with ``path``, ``value``,
    ``original_value`` and ``from``), see ``SPEC.md``. ``names`` maps the
    paths' objects (``roles/123``) to their names at the time of the
    proposal, so that proposals can be rendered after the objects are gone.
    A draft without instructions is a tension. Spelling corrections by the
    Secretary were adopted proposals of their own kind, without the process;
    they're kept in the history, spelling changes through governance now.
    """

    GOVERNANCE = ""
    SPELLING = "spelling"
    # A role's policies for its domains, changed by the role (constitution
    # 1.3.2), see governance/roles/domain_policies.py
    DOMAIN_POLICY = "domain_policy"
    KIND_CHOICES = [
        (GOVERNANCE, _("governance")),
        (SPELLING, _("spelling correction")),
        (DOMAIN_POLICY, _("policy of a domain")),
    ]

    DRAFT = "draft"
    PUBLISHED = "published"
    IN_MEETING = "in_meeting"
    ADOPTED = "adopted"
    WITHDRAWN = "withdrawn"
    STATUS_CHOICES = [
        (DRAFT, _("draft")),
        (PUBLISHED, _("published")),
        (IN_MEETING, _("waiting for a meeting")),
        (ADOPTED, _("adopted")),
        (WITHDRAWN, _("withdrawn")),
    ]

    circle = models.ForeignKey(
        "roles.Role",
        on_delete=models.PROTECT,
        related_name="proposals",
        verbose_name=_("circle"),
    )
    proposer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="proposals",
        verbose_name=_("proposer"),
    )
    kind = models.CharField(
        _("kind"), max_length=20, choices=KIND_CHOICES, blank=True, default=GOVERNANCE
    )
    role = models.ForeignKey(
        "roles.Role",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="proposals_from_role",
        verbose_name=_("role of the proposer"),
        help_text=_(
            "The proposal addresses a tension of one of the proposer's roles."
            " Unknown for proposals imported from GlassFrog."
        ),
    )
    tension = models.TextField(_("tension"), blank=True)
    instructions = models.JSONField(_("instructions"), default=list, blank=True)
    names = models.JSONField(_("names"), default=dict, blank=True)
    status = models.CharField(
        _("status"), max_length=20, choices=STATUS_CHOICES, default=DRAFT
    )
    created_at = models.DateTimeField(_("created at"))
    published_at = models.DateTimeField(_("published at"), null=True, blank=True)
    deadline = models.DateTimeField(_("deadline"), null=True, blank=True)
    decided_at = models.DateTimeField(_("decided at"), null=True, blank=True)
    meeting = models.ForeignKey(
        "meetings.Meeting",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="proposals",
        verbose_name=_("meeting"),
    )
    roles = models.ManyToManyField(
        "roles.Role",
        blank=True,
        related_name="changed_by_proposals",
        verbose_name=_("affected roles"),
    )
    policies = models.ManyToManyField(
        "roles.Policy",
        blank=True,
        related_name="changed_by_proposals",
        verbose_name=_("affected policies"),
    )
    glassfrog_id = models.BigIntegerField(
        _("GlassFrog ID"), null=True, blank=True, unique=True
    )
    glassfrog_tension_id = models.BigIntegerField(
        _("GlassFrog tension ID"), null=True, blank=True, unique=True
    )

    objects = ProposalQuerySet.as_manager()

    class Meta:
        ordering = ["-decided_at", "-created_at", "-pk"]
        verbose_name = _("proposal")
        verbose_name_plural = _("proposals")

    def __str__(self):
        # The first line which isn't a heading of the proposal's sections
        lines = [line.strip() for line in self.tension.splitlines()]
        first_line = next(
            (line for line in lines if line and not line.startswith("#")), ""
        )
        if not first_line:
            # Spelling corrections, and imported elections without a tension
            if self.kind:
                return str(self.get_kind_display()).capitalize()
            return str(_("(no tension)"))
        return Truncator(first_line).chars(100)

    def get_absolute_url(self):
        return reverse("proposal", kwargs={"pk": self.pk})

    @property
    def adopted_on(self):
        """The day the nightly task adopts the published proposal, if nobody
        objects or requests a meeting before"""
        if self.deadline is None:
            return None
        deadline = self.deadline.astimezone(dt.UTC)
        run = dt.datetime.combine(deadline.date(), NIGHTLY_RUN, tzinfo=dt.UTC)
        if deadline > run:
            run += dt.timedelta(days=1)
        return timezone.localdate(run)

    @property
    def is_tension(self):
        return self.status == self.DRAFT and not self.instructions


class Response(models.Model):
    """A circle member's response to a published proposal

    Clarifying questions are comments. Requesting a meeting or objecting
    (with a reason) stops the automatic adoption and moves the proposal to
    the next governance meeting; when every member consented the proposal
    is adopted right away. A member's latest consent, request or objection
    counts.
    """

    COMMENT = "comment"
    CONSENT = "consent"
    MEETING = "meeting"
    # Earlier async objections; objections are raised in the meeting now,
    # where the facilitator tests them
    OBJECTION = "objection"
    KIND_CHOICES = [
        (COMMENT, _("question or comment")),
        (CONSENT, _("no objection")),
        (MEETING, _("discuss in a meeting")),
        (OBJECTION, _("objection")),
    ]

    proposal = models.ForeignKey(
        Proposal,
        on_delete=models.CASCADE,
        related_name="responses",
        verbose_name=_("proposal"),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("user"),
    )
    kind = models.CharField(_("kind"), max_length=20, choices=KIND_CHOICES)
    text = models.TextField(_("text"), blank=True)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]
        verbose_name = _("response")
        verbose_name_plural = _("responses")

    def __str__(self):
        return f"{self.get_kind_display()}: {self.user}"
