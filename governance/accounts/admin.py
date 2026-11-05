from django.contrib import admin
from django.utils import timezone

from governance.accounts.models import APIToken, User
from governance.roles.assignments import end_assignments_of


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ["full_name", "short_name", "email", "is_active", "is_admin"]
    list_filter = ["is_active", "is_admin"]
    search_fields = ["full_name", "short_name", "email"]
    exclude = ["password", "last_login"]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if change and "is_active" in form.changed_data and not obj.is_active:
            # People leaving don't keep their roles
            end_assignments_of(obj, timezone.localdate())


@admin.register(APIToken)
class APITokenAdmin(admin.ModelAdmin):
    """Created on the API tokens page or by ``gov login``, which show the
    secret once; here they can be looked at and deleted"""

    list_display = [
        "title",
        "user",
        "access",
        "created_at",
        "last_used_at",
        "expires_at",
    ]
    list_filter = ["access"]
    search_fields = ["title", "user__full_name", "user__email"]
    readonly_fields = ["user", "access", "key_hash", "created_at", "last_used_at"]

    def has_add_permission(self, request):
        return False
