from django.contrib import admin

from governance.history.models import Change


@admin.register(Change)
class ChangeAdmin(admin.ModelAdmin):
    """Read only: a cache of the audit log's changes (``update_changes()``)"""

    list_display = ["date", "subject", "action", "role", "policy"]
    list_filter = ["subject", "action"]
    search_fields = ["role__name", "policy__title"]
    date_hierarchy = "date"
    raw_id_fields = ["role", "policy"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
