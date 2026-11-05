from django import template
from django.utils import timezone

from governance.meetings.activity import INACTIVITY
from governance.meetings.models import Meeting


register = template.Library()


@register.inclusion_tag("meetings/_running.html", takes_context=True)
def running_meetings(context):
    """The running meetings one attends, on every page except in them;
    not those inactive for hours, they end soon (activity.py)"""
    request = context["request"]
    if not request.user.is_authenticated:
        return {"meetings": []}
    match = request.resolver_match
    current = match.kwargs.get("pk") if match and match.url_name == "meeting" else None
    return {
        "meetings": Meeting.objects
        .running()
        .filter(
            attendees=request.user,
            active_at__gte=timezone.now() - INACTIVITY,
        )
        .exclude(pk=current)
        .select_related("circle")
        .order_by("started_at")
    }
