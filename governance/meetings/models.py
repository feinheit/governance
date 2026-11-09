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

    def of_role(self, role):
        """Its own (a circle's, or a role's for its inside), the ad hoc
        tactical meetings it was invited to, and a role's (not a circle's)
        those of its circle, which invite all its roles (constitution 3.1;
        GlassFrog's tactical meetings came without invited roles)"""
        # A super-circle's regular tactical meetings invite its sub-circles
        # too, only ad hoc ones count
        meetings = Q(circle=role) | Q(circle=None, invited_roles=role)
        if not role.is_circle and role.circle_id:
            from governance.history.models import Change

            # Since it moved into the circle, if it did
            moved_in = (
                Change.objects
                .filter(role=role, kind="moved", new=role.circle_id)
                .order_by("-date")
                .values_list("date", flat=True)
                .first()
            )
            circle = Q(circle=role.circle_id)
            if moved_in:
                circle &= Q(started_at__date__gte=moved_in)
            meetings |= circle
        return self.filter(meetings).distinct()


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
        # Within sentences ("Outputs of the …"), ad hoc ones apart
        kind = (
            _("ad hoc tactical meeting") if self.is_ad_hoc else self.get_kind_display()
        )
        return " ".join(filter(None, [str(kind), str(self.circle or "")]))

    def get_absolute_url(self):
        return reverse("meeting", kwargs={"pk": self.pk})

    @property
    def is_ad_hoc(self):
        """A tactical meeting called with any roles, not a circle's (3.1)"""
        return self.kind == self.TACTICAL and self.circle_id is None

    @property
    def kind_label(self):
        """The kind, ad hoc tactical meetings apart"""
        if self.is_ad_hoc:
            return _("Ad hoc Tactical Meeting")
        return self.get_kind_display()

    @property
    def kind_key(self):
        """For the badge's tone: ``ad-hoc``, ``governance``, ``tactical``"""
        return "ad-hoc" if self.is_ad_hoc else self.kind

    @property
    def steps(self):
        return (
            TACTICAL_STEP_CHOICES
            if self.kind == self.TACTICAL
            else GOVERNANCE_STEP_CHOICES
        )

    @property
    def processing_step(self):
        """The step processing the agenda's items: only then an item is
        active (the current one)"""
        return "tensions" if self.kind == self.TACTICAL else "agenda"

    @property
    def active_item_id(self):
        """The current item, while the meeting processes the agenda"""
        if self.is_running and self.step == self.processing_step:
            return self.current_item_id
        return None

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
    # Removing the item puts a draft or an async proposal back
    proposal_status = models.CharField(_("proposal status"), max_length=20, blank=True)
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

    def complete(self):
        """Processed; no longer the meeting's current item"""
        self.is_completed = True
        self.save(update_fields=["is_completed"])
        meeting = self.meeting
        if meeting.current_item_id == self.pk:
            meeting.current_item = None
            meeting.save(update_fields=["current_item"])

    complete.alters_data = True


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
    # What recording it changed, so that a correction in the meeting undoes
    # it (``elections.undo_election()``): a new assignment or the Role Lead's
    # previous term, and the assignments it ended
    started = models.BooleanField(default=True, editable=False)
    previous_term = models.DateField(null=True, blank=True, editable=False)
    replaced = models.JSONField(default=list, blank=True, editable=False)

    class Meta:
        ordering = ["created_at", "pk"]
        verbose_name = _("election")
        verbose_name_plural = _("elections")

    def __str__(self):
        return f"{self.role}: {self.user}"
