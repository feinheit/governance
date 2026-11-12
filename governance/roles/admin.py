from django.contrib import admin

from governance.roles import models


class AccountabilityInline(admin.TabularInline):
    model = models.Accountability
    extra = 0


class DomainInline(admin.TabularInline):
    model = models.Domain
    extra = 0


class AssignmentInline(admin.TabularInline):
    model = models.Assignment
    extra = 0
    raw_id_fields = ["user"]


@admin.register(models.Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ["name", "circle", "is_circle", "core_role", "archived_on"]
    list_filter = ["is_circle", "core_role", "archived_on"]
    search_fields = ["name", "purpose"]
    raw_id_fields = ["circle"]
    inlines = [DomainInline, AccountabilityInline, AssignmentInline]


@admin.register(models.Policy)
class PolicyAdmin(admin.ModelAdmin):
    list_display = ["title", "role", "archived_on"]
    list_filter = ["archived_on"]
    search_fields = ["title", "body"]
    raw_id_fields = ["role", "domain"]


@admin.register(models.Metric, models.ChecklistItem)
class RoleItemAdmin(admin.ModelAdmin):
    list_display = ["description", "role", "frequency"]
    raw_id_fields = ["role"]


@admin.register(models.Accountability, models.Domain)
class TextAdmin(admin.ModelAdmin):
    list_display = ["text", "role", "position"]
    search_fields = ["text", "role__name"]
    raw_id_fields = ["role"]


@admin.register(models.Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ["user", "role", "focus", "starts_on", "ends_on", "elected_until"]
    list_filter = ["ends_on"]
    search_fields = ["user__full_name", "user__email", "role__name", "focus"]
    raw_id_fields = ["role", "user"]


@admin.register(models.Link)
class LinkAdmin(admin.ModelAdmin):
    list_display = ["title", "role", "url"]
    search_fields = ["title", "url", "description"]
    raw_id_fields = ["role"]


@admin.register(models.Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = ["title", "role"]
    search_fields = ["title", "body"]
    raw_id_fields = ["role"]
