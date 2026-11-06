from django.contrib import admin

from governance.meetings.models import AgendaItem, Election, Meeting, Objection


class AgendaItemInline(admin.TabularInline):
    model = AgendaItem
    extra = 0
    fields = ["position", "label", "owner", "proposal", "is_completed", "outcome"]
    raw_id_fields = ["owner", "proposal"]


class ElectionInline(admin.TabularInline):
    model = Election
    extra = 0
    raw_id_fields = ["role", "user"]


class ObjectionInline(admin.TabularInline):
    model = Objection
    extra = 0
    fields = ["proposal", "user", "role", "text", "is_valid", "is_integrated"]
    raw_id_fields = ["proposal", "user", "role"]


@admin.register(Meeting)
class MeetingAdmin(admin.ModelAdmin):
    list_display = ["__str__", "kind", "circle", "started_at", "ended_at"]
    list_filter = ["kind"]
    search_fields = ["circle__name", "minutes"]
    date_hierarchy = "started_at"
    raw_id_fields = [
        "circle",
        "secretary",
        "called_by",
        "current_item",
        "invited_roles",
        "attendees",
    ]
    inlines = [AgendaItemInline, ElectionInline, ObjectionInline]


@admin.register(AgendaItem)
class AgendaItemAdmin(admin.ModelAdmin):
    list_display = ["label", "meeting", "owner", "is_completed"]
    list_filter = ["is_completed"]
    search_fields = ["label", "outcome"]
    raw_id_fields = ["meeting", "owner", "proposal"]


@admin.register(Objection)
class ObjectionAdmin(admin.ModelAdmin):
    list_display = ["proposal", "user", "role", "is_valid", "is_integrated"]
    list_filter = ["is_valid", "is_integrated"]
    search_fields = ["text", "user__full_name"]
    raw_id_fields = ["proposal", "meeting", "user", "role", "response"]


@admin.register(Election)
class ElectionAdmin(admin.ModelAdmin):
    list_display = ["role", "user", "term_ends_on", "meeting"]
    search_fields = ["role__name", "user__full_name"]
    raw_id_fields = ["meeting", "role", "user"]
