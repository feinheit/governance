from django.conf import settings
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils.translation import gettext_lazy as _


# The process of tactical meetings (constitution, article 3)
TACTICAL_STEP_CHOICES = [
    ("check_in", _("Check-in round")),
    ("checklists", _("Checklist review")),
    ("metrics", _("Metrics review")),
    ("progress", _("Progress updates")),
    ("agenda", _("Agenda building")),
    ("tensions", _("Triage issues")),
    ("closing", _("Closing round")),
]

# The process of governance meetings (constitution 5.4.3): the agenda's items
# are processed in any order the facilitator chooses, elections first if
# somebody asks for it
GOVERNANCE_STEP_CHOICES = [
    ("check_in", _("Check-in round")),
    ("agenda", _("Agenda building and processing")),
    ("closing", _("Closing round")),
]

MEETING_STEP_CHOICES = list(
    dict(TACTICAL_STEP_CHOICES + GOVERNANCE_STEP_CHOICES).items()
)


class MeetingQuerySet(models.QuerySet):
    def running(self):
        return self.filter(ended_at=None, started_at__isnull=False)


class Meeting(models.Model):
    GOVERNANCE = "governance"
    TACTICAL = "tactical"
    KIND_CHOICES = [
        (GOVERNANCE, _("governance meeting")),
        (TACTICAL, _("tactical meeting")),
    ]

    circle = models.ForeignKey(
        "roles.Role",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="meetings",
        verbose_name=_("circle"),
        help_text=_("Unknown for some meetings imported from GlassFrog."),
    )
    kind = models.CharField(_("kind"), max_length=20, choices=KIND_CHOICES)
    started_at = models.DateTimeField(_("started at"), null=True, blank=True)
    ended_at = models.DateTimeField(_("ended at"), null=True, blank=True)
    # meetings/activity.py, meetings inactive for hours end
    active_at = models.DateTimeField(_("last active at"), null=True, blank=True)
    minutes = models.TextField(_("minutes"), blank=True)
    # The members run the meeting, the secretary amends proposals (the app
    # doesn't need to know who facilitates)
    secretary = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("secretary"),
    )
    called_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("called by"),
    )
    invited_roles = models.ManyToManyField(
        "roles.Role",
        blank=True,
        related_name="invited_to_meetings",
        verbose_name=_("invited roles"),
        help_text=_("Tactical meetings: the roles which are invited."),
    )
    step = models.CharField(
        _("step"), max_length=20, choices=MEETING_STEP_CHOICES, blank=True
    )
    attendees = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="attended_meetings",
        verbose_name=_("attendees"),
        help_text=_("By default the circle's members; others may be invited."),
    )
    current_item = models.ForeignKey(
        "AgendaItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("current agenda item"),
    )
    # Unique per kind, governance and tactical meetings have their own IDs
    glassfrog_id = models.BigIntegerField(_("GlassFrog ID"), null=True, blank=True)

    objects = MeetingQuerySet.as_manager()

    class Meta:
        ordering = ["-started_at", "-pk"]
        verbose_name = _("meeting")
        verbose_name_plural = _("meetings")
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "glassfrog_id"], name="unique_glassfrog_meeting"
            ),
            # Ad-hoc tactical meetings have no circle, they may run any time
            models.UniqueConstraint(
                fields=["circle"],
                condition=Q(ended_at=None, started_at__isnull=False),
                name="one_running_meeting_per_circle",
            ),
        ]

    def __str__(self):
        return " ".join(filter(None, [self.get_kind_display(), str(self.circle or "")]))

    def get_absolute_url(self):
        return reverse("meeting", kwargs={"pk": self.pk})

    @property
    def steps(self):
        return (
            TACTICAL_STEP_CHOICES
            if self.kind == self.TACTICAL
            else GOVERNANCE_STEP_CHOICES
        )

    @property
    def is_running(self):
        return bool(self.started_at and not self.ended_at)


# The steps of integrative decision-making (constitution, article 5)
STEP_CHOICES = [
    ("present", _("Present proposal")),
    ("questions", _("Clarifying questions")),
    ("reactions", _("Reaction round")),
    ("amend", _("Amend and clarify")),
    ("objections", _("Objection round")),
    ("integration", _("Integration")),
]


class AgendaItem(models.Model):
    meeting = models.ForeignKey(
        Meeting,
        on_delete=models.CASCADE,
        related_name="agenda_items",
        verbose_name=_("meeting"),
    )
    position = models.PositiveIntegerField(_("position"), default=0)
    label = models.CharField(_("label"), max_length=500, blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("owner"),
    )
    proposal = models.ForeignKey(
        "proposals.Proposal",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agenda_items",
        verbose_name=_("proposal"),
    )
    is_completed = models.BooleanField(_("is completed"), default=False)
    step = models.CharField(_("step"), max_length=20, choices=STEP_CHOICES, blank=True)
    outcome = models.TextField(
        _("outcome"),
        blank=True,
        help_text=_("Tactical meetings: what was decided or requested."),
    )
    link = models.URLField(
        _("link"),
        max_length=1000,
        blank=True,
        help_text=_("E.g. the task created for it."),
    )
    glassfrog_id = models.BigIntegerField(_("GlassFrog ID"), null=True, blank=True)

    class Meta:
        ordering = ["position", "pk"]
        verbose_name = _("agenda item")
        verbose_name_plural = _("agenda items")

    def __str__(self):
        return self.label or str(self.proposal or "")


class Objection(models.Model):
    """An objection raised in a governance meeting, with the facilitator's
    test (is it valid?) and whether integrating it resolved it"""

    proposal = models.ForeignKey(
        "proposals.Proposal",
        on_delete=models.CASCADE,
        related_name="objections",
        verbose_name=_("proposal"),
    )
    meeting = models.ForeignKey(
        Meeting,
        on_delete=models.CASCADE,
        related_name="objections",
        verbose_name=_("meeting"),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("raised by"),
    )
    role = models.ForeignKey(
        "roles.Role",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("role of the objector"),
        help_text=_(
            "An objection is raised for a role the objector represents in the"
            " circle (constitution 5.3)."
        ),
    )
    text = models.TextField(_("reason"))
    is_valid = models.BooleanField(
        _("is valid"),
        null=True,
        blank=True,
        help_text=_("The facilitator's test, empty until tested."),
    )
    is_integrated = models.BooleanField(_("is integrated"), default=False)
    response = models.OneToOneField(
        "proposals.Response",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="meeting_objection",
        verbose_name=_("raised async"),
        help_text=_("The async response the objection comes from."),
    )
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]
        verbose_name = _("objection")
        verbose_name_plural = _("objections")

    def __str__(self):
        return self.text

    @property
    def is_open(self):
        """Blocks adopting the proposal

        Objections raised async can only be tested if their objector is
        there; untested, they don't block.
        """
        if self.is_valid is None:
            return self.response_id is None
        return self.is_valid and not self.is_integrated


class Election(models.Model):
    """The result of an election in a governance meeting

    No nomination round in the app; recording the result creates the
    assignment with the term.
    """

    meeting = models.ForeignKey(
        Meeting,
        on_delete=models.CASCADE,
        related_name="elections",
        verbose_name=_("meeting"),
    )
    role = models.ForeignKey(
        "roles.Role",
        on_delete=models.PROTECT,
        related_name="elections",
        verbose_name=_("role"),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("elected"),
    )
    term_ends_on = models.DateField(_("term ends on"))
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]
        verbose_name = _("election")
        verbose_name_plural = _("elections")

    def __str__(self):
        return f"{self.role}: {self.user}"
