from collections import defaultdict

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from governance.roles.constitution import (
    CORE_ROLE_CHOICES,
    CORE_ROLES,
    FACILITATOR,
    LEAD,
    REP,
    SECRETARY,
)


class RoleQuerySet(models.QuerySet):
    def active(self):
        return self.filter(archived_on__isnull=True)

    def circles(self):
        return self.filter(is_circle=True)

    def depth_first(self):
        """The circles in depth-first order, with their ``depth``"""
        children = defaultdict(list)
        for circle in self.active().circles().order_by("position", "name"):
            children[circle.circle_id].append(circle)
        result = []

        def walk(parent, depth):
            for circle in children[parent]:
                circle.depth = depth
                result.append(circle)
                walk(circle.pk, depth + 1)

        walk(None, 0)
        return result


class Role(models.Model):
    """A role, or a circle: a role broken down into roles

    The anchor circle is the only role without a circle. Circles have the
    core roles (Circle Lead, Facilitator, Secretary, and except for the
    anchor circle Circle Rep).
    """

    circle = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="roles",
        verbose_name=_("circle"),
    )
    name = models.CharField(_("name"), max_length=200)
    purpose = models.TextField(_("purpose"), blank=True)
    position = models.PositiveIntegerField(_("position"), default=0)
    core_role = models.CharField(
        _("core role"), max_length=20, choices=CORE_ROLE_CHOICES, blank=True
    )

    is_circle = models.BooleanField(_("is a circle"), default=False)
    short_name = models.CharField(_("short name"), max_length=100, blank=True)
    strategy = models.TextField(_("strategy"), blank=True)
    async_acceptance_days = models.PositiveSmallIntegerField(
        _("acceptance period of async proposals"),
        null=True,
        blank=True,
        help_text=_("In calendar days. Inherited from the super-circle if empty."),
    )

    is_elected_by_policy = models.BooleanField(
        _("elected by policy"),
        default=False,
        help_text=_(
            "A policy makes the role elected; the policy stays the explanation."
        ),
    )
    archived_on = models.DateField(_("archived on"), null=True, blank=True)
    other_names = models.JSONField(
        _("other names"),
        default=list,
        blank=True,
        help_text=_("Earlier names and short names, texts may still mention them."),
    )
    glassfrog_id = models.BigIntegerField(
        _("GlassFrog ID"), null=True, blank=True, unique=True
    )
    glassfrog_circle_id = models.BigIntegerField(
        _("GlassFrog circle ID"), null=True, blank=True, unique=True
    )

    objects = RoleQuerySet.as_manager()

    class Meta:
        ordering = ["position", "name", "pk"]
        verbose_name = _("role")
        verbose_name_plural = _("roles")
        constraints = [
            models.UniqueConstraint(
                fields=["circle", "core_role"],
                condition=~Q(core_role="") & Q(archived_on__isnull=True),
                name="unique_core_role_per_circle",
            ),
            models.CheckConstraint(
                condition=Q(is_circle=False) | Q(core_role=""),
                name="core_roles_are_no_circles",
            ),
        ]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("role", kwargs={"pk": self.pk})

    @property
    def core(self):
        return CORE_ROLES.get(self.core_role)

    @property
    def display_purpose(self):
        if self.core_role == LEAD:
            return self.circle.purpose if self.circle else ""
        return self.core.purpose if self.core else self.purpose

    @property
    def is_elected(self):
        if self.core:
            return self.core.is_elected
        return self.is_elected_by_policy and not self.is_circle

    def ancestors(self):
        """The circles containing this role, outermost first"""
        circles = []
        circle = self.circle
        while circle is not None:
            circles.append(circle)
            circle = circle.circle
        return circles[::-1]

    def effective_async_acceptance_days(self, default=4):
        circle = self if self.is_circle else self.circle
        while circle is not None:
            if circle.async_acceptance_days is not None:
                return circle.async_acceptance_days
            circle = circle.circle
        return default

    def create_core_roles(self):
        """Creates the missing core roles of a circle"""
        keys = [LEAD, FACILITATOR, SECRETARY] + ([REP] if self.circle_id else [])
        existing = set(self.roles.active().values_list("core_role", flat=True))
        for position, key in enumerate(keys):
            if key not in existing:
                Role.objects.create(
                    circle=self,
                    core_role=key,
                    name=str(CORE_ROLES[key].name),
                    position=position,
                )


class Accountability(models.Model):
    role = models.ForeignKey(
        Role,
        on_delete=models.CASCADE,
        related_name="accountabilities",
        verbose_name=_("role"),
    )
    text = models.TextField(_("text"))
    position = models.PositiveIntegerField(_("position"), default=0)
    glassfrog_id = models.BigIntegerField(
        _("GlassFrog ID"), null=True, blank=True, unique=True
    )

    class Meta:
        ordering = ["position", "pk"]
        verbose_name = _("accountability")
        verbose_name_plural = _("accountabilities")

    def __str__(self):
        return self.text


class Domain(models.Model):
    role = models.ForeignKey(
        Role, on_delete=models.CASCADE, related_name="domains", verbose_name=_("role")
    )
    text = models.TextField(_("text"))
    position = models.PositiveIntegerField(_("position"), default=0)
    glassfrog_id = models.BigIntegerField(
        _("GlassFrog ID"), null=True, blank=True, unique=True
    )

    class Meta:
        ordering = ["position", "pk"]
        verbose_name = _("domain")
        verbose_name_plural = _("domains")

    def __str__(self):
        return self.text


class PolicyQuerySet(models.QuerySet):
    def active(self):
        return self.filter(archived_on__isnull=True)


class Policy(models.Model):
    """A policy of a circle, or of a role for its domains"""

    role = models.ForeignKey(
        Role, on_delete=models.PROTECT, related_name="policies", verbose_name=_("role")
    )
    title = models.CharField(_("title"), max_length=200)
    body = models.TextField(_("body"), blank=True)
    domain = models.ForeignKey(
        Domain,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="policies",
        verbose_name=_("domain"),
    )
    position = models.PositiveIntegerField(_("position"), default=0)
    archived_on = models.DateField(_("archived on"), null=True, blank=True)
    glassfrog_id = models.BigIntegerField(
        _("GlassFrog ID"), null=True, blank=True, unique=True
    )

    objects = PolicyQuerySet.as_manager()

    class Meta:
        ordering = ["position", "title", "pk"]
        verbose_name = _("policy")
        verbose_name_plural = _("policies")

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("policy", kwargs={"pk": self.pk})


class AssignmentQuerySet(models.QuerySet):
    def current(self, *, on=None):
        from django.utils import timezone

        day = on or timezone.localdate()
        return self.filter(
            Q(starts_on__isnull=True) | Q(starts_on__lte=day),
            Q(ends_on__isnull=True) | Q(ends_on__gt=day),
        )


class Assignment(models.Model):
    """A person holding a role, optionally with a focus

    Ending an assignment keeps the row. ``ends_on`` is the first day the
    person doesn't hold the role anymore.
    """

    role = models.ForeignKey(
        Role,
        on_delete=models.CASCADE,
        related_name="assignments",
        verbose_name=_("role"),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assignments",
        verbose_name=_("user"),
    )
    focus = models.CharField(_("focus"), max_length=200, blank=True)
    elected_until = models.DateField(_("elected until"), null=True, blank=True)
    starts_on = models.DateField(_("starts on"), null=True, blank=True)
    ends_on = models.DateField(_("ends on"), null=True, blank=True)
    glassfrog_id = models.BigIntegerField(
        _("GlassFrog ID"), null=True, blank=True, unique=True
    )

    objects = AssignmentQuerySet.as_manager()

    class Meta:
        ordering = ["starts_on", "pk"]
        verbose_name = _("assignment")
        verbose_name_plural = _("assignments")

    def __str__(self):
        return f"{self.user} – {self.role}"


# Like GlassFrog: the frequencies only group checklist items and metrics
FREQUENCY_CHOICES = [
    ("weekly", _("weekly")),
    ("monthly", _("monthly")),
    ("quarterly", _("quarterly")),
    ("yearly", _("yearly")),
]


def by_frequency(items, *, frequency=lambda item: item.frequency):
    """``(label, items)`` in the order of the frequencies, those without one
    last"""
    groups = {key: [] for key, _label in [*FREQUENCY_CHOICES, ("", "")]}
    for item in items:
        groups.setdefault(frequency(item), []).append(item)
    labels = dict(FREQUENCY_CHOICES) | {"": _("without frequency")}
    return [(labels.get(key, key), group) for key, group in groups.items() if group]


class RoleItem(models.Model):
    """Something a role reports in the tactical meetings it's invited to

    A circle's own items belong to the circle.
    """

    role = models.ForeignKey(
        Role,
        on_delete=models.CASCADE,
        related_name="%(class)ss",
        verbose_name=_("role"),
    )
    description = models.TextField(_("description"))
    frequency = models.CharField(
        _("frequency"), max_length=20, choices=FREQUENCY_CHOICES, blank=True
    )
    link = models.URLField(_("link"), max_length=1000, blank=True)
    position = models.PositiveIntegerField(_("position"), default=0)
    glassfrog_id = models.BigIntegerField(
        _("GlassFrog ID"), null=True, blank=True, unique=True
    )

    class Meta:
        abstract = True
        ordering = ["position", "pk"]

    def __str__(self):
        return self.description


class Metric(RoleItem):
    class Meta(RoleItem.Meta):
        verbose_name = _("metric")
        verbose_name_plural = _("metrics")


class ChecklistItem(RoleItem):
    class Meta(RoleItem.Meta):
        verbose_name = _("checklist item")
        verbose_name_plural = _("checklist items")


class Link(models.Model):
    """A link to an external tool of a circle or role, e.g. where projects
    and actions are managed (a to-do management tool, a board)"""

    role = models.ForeignKey(
        Role, on_delete=models.CASCADE, related_name="links", verbose_name=_("role")
    )
    title = models.CharField(_("title"), max_length=200)
    url = models.URLField(_("URL"), max_length=1000)
    description = models.CharField(_("description"), max_length=500, blank=True)
    position = models.PositiveIntegerField(_("position"), default=0)

    class Meta:
        ordering = ["position", "pk"]
        verbose_name = _("link")
        verbose_name_plural = _("links")

    def __str__(self):
        return self.title
