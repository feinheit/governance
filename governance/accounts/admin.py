from django.contrib import admin

from governance.accounts.models import User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ["full_name", "short_name", "email", "is_active", "is_admin"]
    list_filter = ["is_active", "is_admin"]
    search_fields = ["full_name", "short_name", "email"]
    exclude = ["password", "last_login"]
