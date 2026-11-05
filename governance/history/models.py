from django.db import models
from django.utils.translation import gettext_lazy as _


class SnapshotQuerySet(models.QuerySet):
    def on(self, day):
        """The snapshot valid on the given day (the last one up to it)"""
        return self.filter(date__lte=day).order_by("-date").first()


class Snapshot(models.Model):
    """The normalized governance of a day, valid until the next snapshot

    ``data`` has ``roles`` (with their texts and holders) and ``policies``,
    keyed by primary keys, see ``governance.history.snapshots``.
    """

    date = models.DateField(_("date"), unique=True)
    data = models.JSONField(_("data"))

    objects = SnapshotQuerySet.as_manager()

    class Meta:
        ordering = ["-date"]
        verbose_name = _("snapshot")
        verbose_name_plural = _("snapshots")

    def __str__(self):
        return str(self.date)


class Change(models.Model):
    """A difference between a snapshot and the one before

    Computed from the snapshots (``update_changes()``), so that the history
    shows what changed also without a proposal (e.g. in GlassFrog outside
    governance) and who held which role when.
    """

    date = models.DateField(_("date"), db_index=True)
    role = models.ForeignKey(
        "roles.Role",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="changes",
        verbose_name=_("role"),
    )
    policy = models.ForeignKey(
        "roles.Policy",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="changes",
        verbose_name=_("policy"),
    )
    kind = models.CharField(_("kind"), max_length=40)
    old = models.JSONField(_("old"), null=True, blank=True)
    new = models.JSONField(_("new"), null=True, blank=True)

    class Meta:
        ordering = ["-date", "pk"]
        verbose_name = _("change")
        verbose_name_plural = _("changes")

    def __str__(self):
        return f"{self.date} {self.kind}"
