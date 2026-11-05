from django.db import models
from django.utils.translation import gettext_lazy as _


class Change(models.Model):
    """A difference between the structure of a day and the day before

    Computed from the audit log (``update_changes()``), so that the history
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
