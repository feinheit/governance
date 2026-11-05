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
    inlines = [AccountabilityInline, DomainInline, AssignmentInline]


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
