from django import template
from django.utils.html import format_html, strip_tags
from django.utils.safestring import mark_safe
from django.utils.translation import gettext
from markdown_it import MarkdownIt

from governance.roles.mentions import render_mentions


register = template.Library()

# Light Markdown like GlassFrog: no HTML, links are made clickable
_markdown = MarkdownIt("commonmark", {"html": False, "linkify": True, "breaks": True})
_markdown.enable(["linkify", "strikethrough"])


@register.filter
def markdown(text):
    return mark_safe(_markdown.render(render_mentions(str(text or ""))))


@register.filter
def plain(text):
    """The text without Markdown and mention syntax, e.g. for snippets"""
    return " ".join(strip_tags(markdown(text)).split())


@register.filter(name="by_frequency")
def by_frequency_filter(items):
    """Checklist items or metrics grouped by their frequency"""
    from governance.roles.models import by_frequency

    return by_frequency(items)


@register.filter
def elevated(right):
    """Why somebody may do what the constitution leaves to others, a right
    of roles.permissions: as admin, or as Secretary standing in for the
    Circle Leads; empty otherwise"""
    from governance.roles.permissions import AS_ADMIN, AS_SECRETARY

    if right == AS_ADMIN:
        return gettext("As admin")
    if right == AS_SECRETARY:
        return gettext("As Secretary, standing in for the Circle Leads")
    return ""


@register.simple_tag
def button_class(right, style="btn-quiet", size="btn-sm"):
    """The attributes of a button needing ``right``: marked (btn-elevated,
    with the reason as its title) when the right is elevated(), else in
    ``style``, e.g. btn-destructive"""
    if reason := elevated(right):
        return format_html('class="btn {} btn-elevated" title="{}"', size, reason)
    return format_html('class="btn {} {}"', size, style)


# The colors of badges (main.css): states of proposals, kinds of responses,
# actions of changes (proposals/describe.py) and kinds of history.Change;
# removing isn't bad (it may be a good cleanup), only objections are red
TONES = {
    "draft": "neutral",
    "published": "warning",
    "in_meeting": "info",
    "adopted": "success",
    "withdrawn": "neutral",
    "consent": "success",
    "objection": "danger",
    "meeting": "warning",
    "comment": "info",
    "added": "success",
    "assigned": "success",
    "removed": "neutral",
    "unassigned": "neutral",
    "reelected": "core",
    "elected": "core",
    # Meetings, and the special kinds of proposals
    "governance": "core",
    "tactical": "info",
    "spelling": "neutral",
    "domain_policy": "neutral",
}


@register.filter
def tone(value):
    """The badge's class for a state or kind: ``badge {{ x.status|tone }}``"""
    value = str(value)
    if value not in TONES:
        value = value.rsplit("-", 1)[-1]  # accountabilities-added
    return f"wb-tone-{TONES.get(value, 'info')}"
