from django.contrib import admin

from governance.proposals.models import Proposal, Response


class ResponseInline(admin.TabularInline):
    model = Response
    extra = 0
    raw_id_fields = ["user"]


@admin.register(Proposal)
class ProposalAdmin(admin.ModelAdmin):
    list_display = [
        "__str__",
        "circle",
        "status",
        "kind",
        "proposer",
        "created_at",
        "decided_at",
    ]
    list_filter = ["status", "kind"]
    search_fields = ["tension", "circle__name", "proposer__full_name"]
    date_hierarchy = "created_at"
    raw_id_fields = ["circle", "proposer", "role", "meeting", "roles", "policies"]
    inlines = [ResponseInline]


@admin.register(Response)
class ResponseAdmin(admin.ModelAdmin):
    list_display = ["proposal", "user", "kind", "created_at"]
    list_filter = ["kind"]
    search_fields = ["text", "user__full_name"]
    raw_id_fields = ["proposal", "user"]
