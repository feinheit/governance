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


@register.filter(name="diff")
def diff_filter(old, new):
    """The changed Markdown text with the words removed and added marked"""
    from governance.diff import diff

    return diff(old, new)


@register.filter
def plain(text):
    """The text without Markdown and mention syntax, e.g. for snippets"""
    return " ".join(strip_tags(markdown(text)).split())


@register.filter(name="plain_mentions")
def plain_mentions_filter(text):
    """The mentions as "@" and the roles' current names, keeping the lines,
    e.g. for plain text mails"""
    from governance.roles.mentions import plain_mentions

    return plain_mentions(str(text or ""))


@register.filter(name="by_frequency")
def by_frequency_filter(items):
    """Checklist items or metrics grouped by their frequency"""
    from governance.roles.models import by_frequency

    return by_frequency(items)


@register.simple_tag
def icon(name):
    """A Bootstrap Icon (frontend/styles/icons.css lists those in use),
    hidden from screen readers: the button's label or title says it"""
    return format_html('<i class="bi bi-{}" aria-hidden="true"></i>', name)


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
def button_class(right, style="btn-quiet", size="btn-sm", title=""):
    """The attributes of a button needing ``right``: marked (btn-elevated,
    with the reason in its title) when the right is elevated(), else in
    ``style``, e.g. btn-destructive; ``title``, e.g. of icon-only buttons"""
    if reason := elevated(right):
        title = f"{title} – {reason}" if title else reason
        style = "btn-elevated"
    if title:
        return format_html('class="btn {} {}" title="{}"', size, style, title)
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
    # Not a circle's: very different, an outline (main.css)
    "ad-hoc": "ad-hoc",
}


@register.filter
def tone(value):
    """The badge's class for a state or kind: ``badge {{ x.status|tone }}``"""
    value = str(value)
    if value not in TONES:
        value = value.rsplit("-", 1)[-1]  # accountabilities-added
    return f"wb-tone-{TONES.get(value, 'info')}"
