import re

from django.contrib.postgres.fields import HStoreField
from django.db import models
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _


class LoggedActionQuerySet(models.QuerySet):
    def for_model(self, model):
        return self.filter(table_name=model._meta.db_table)

    def for_instance(self, instance):
        return self.for_model(type(instance)).filter(row_data__id=str(instance.pk))


def audit_user_id(user_name):
    match = re.search(r"^user-([0-9]+)-", user_name or "")
    return int(match.groups()[0]) if match else None


class LoggedAction(models.Model):
    """Filled by the trigger in ``audit.sql``, see ``audit_audit_table()``"""

    ACTION_TYPES = (
        ("I", "INSERT"),
        ("U", "UPDATE"),
        ("D", "DELETE"),
        ("T", "TRUNCATE"),
    )

    event_id = models.IntegerField(primary_key=True)
    table_name = models.TextField()
    user_name = models.TextField(null=True)  # noqa: DJ001
    created_at = models.DateTimeField()
    action = models.CharField(max_length=1, choices=ACTION_TYPES)
    row_data = HStoreField(null=True)
    changed_fields = HStoreField(null=True)

    objects = LoggedActionQuerySet.as_manager()

    class Meta:
        managed = False
        db_table = "audit_logged_actions"
        ordering = ["event_id"]
        verbose_name = _("logged action")
        verbose_name_plural = _("logged actions")

    def __str__(self):
        return f"{self.get_action_display()} {self.table_name} by {self.user_name} at {self.created_at}"

    @cached_property
    def user_id(self):
        return audit_user_id(self.user_name)
