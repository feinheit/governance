from django.contrib import admin

from governance.accounts.models import APIToken, User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ["full_name", "short_name", "email", "is_active", "is_admin"]
    list_filter = ["is_active", "is_admin"]
    search_fields = ["full_name", "short_name", "email"]
    exclude = ["password", "last_login"]


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
