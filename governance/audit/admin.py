from governance import admin
from governance.audit.models import LoggedAction


@admin.register(LoggedAction)
class LoggedActionAdmin(admin.ModelAdmin):
    """The audit log, read only: the trigger writes it (``audit.sql``)"""

    list_display = ["event_id", "created_at", "table_name", "action", "user_name"]
    list_filter = ["table_name", "action"]
    search_fields = ["user_name"]
    date_hierarchy = "created_at"
    ordering = ["-event_id"]
