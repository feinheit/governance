"""Mentions of roles in texts: ``@[Name](role:123)``

Texts mention roles by their ID so that renaming a role updates them; they
are rendered as links with the current name (the GlassFrog import converted
GlassFrog's plain text mentions).
"""

import re

from django.urls import reverse


MENTION = re.compile(r"@\[([^\]]*)\]\(role:(\d+)\)")


def plain_mentions(text):
    """The mentions as "@" and the roles' current names, e.g. for titles and
    the subjects of mails"""
    from governance.roles.models import Role

    ids = {int(match[2]) for match in MENTION.finditer(text)}
    if not ids:
        return text
    names = dict(Role.objects.filter(pk__in=ids).values_list("pk", "name"))
    return MENTION.sub(lambda match: f"@{names.get(int(match[2]), match[1])}", text)


def render_mentions(text):
    """Markdown links with the roles' current names"""
    from governance.roles.models import Role

    ids = {int(match[2]) for match in MENTION.finditer(text)}
    if not ids:
        return text
    roles = Role.objects.in_bulk(ids)

    def link(match):
        role = roles.get(int(match[2]))
        if role is None:
            return f"@{match[1]}"
        return f"[@{role.name}]({reverse('role', kwargs={'pk': role.pk})})"

    return MENTION.sub(link, text)
