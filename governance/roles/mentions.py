"""Mentions of roles in texts: ``@[Name](role:123)``

Texts mention roles by their ID so that renaming a role updates them; they
are rendered as links with the current name. GlassFrog's texts mention
roles as plain text (``@Koordinator:in Küche``), names contain
spaces and colons, so the longest matching name wins, preferring the roles
of the circle and its super-circles.
"""

import re

from django.urls import reverse


MENTION = re.compile(r"@\[([^\]]*)\]\(role:(\d+)\)")
# Links to GlassFrog roles pasted into texts, e.g. [@Name](https://…/roles/123)
GLASSFROG_LINK = re.compile(r"\[@([^\]]+)\]\([^)]*/roles/(\d+)[^)]*\)")


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


class MentionResolver:
    """Converts plain text mentions into ``@[Name](role:ID)``

    ``aliases`` maps role IDs to other names the texts may use (earlier
    names, short names of circles). GlassFrog writes spaces in mentions as
    underscores.
    """

    def __init__(self, roles, aliases=None):
        roles = [role for role in roles if role.name]
        self.by_glassfrog_id = {
            role.glassfrog_id: role for role in roles if role.glassfrog_id
        }
        self.names = [(role, role.name, True) for role in roles]
        by_pk = {role.pk: role for role in roles}
        for pk, names in (aliases or {}).items():
            if pk in by_pk:
                self.names.extend((by_pk[pk], name, False) for name in names if name)
        self.unresolved = []

    def candidates(self, text, context):
        """``(role, length)`` of names ``text`` starts with, the best first"""
        folded = text.replace("_", " ").casefold()
        chain = (
            ({r.pk for r in context.ancestors()} | {context.pk}) if context else set()
        )
        found = []
        for role, name, is_current in self.names:
            length = len(name)
            if folded.startswith(name.casefold()) and not re.match(
                r"\w", text[length : length + 1]
            ):
                in_chain = role.circle_id in chain or role.pk in chain
                rank = (
                    -length,
                    role.archived_on is not None,
                    not is_current,
                    not in_chain,
                )
                found.append((rank, role, length))
        return [
            (role, length) for _rank, role, length in sorted(found, key=lambda x: x[0])
        ]

    def convert(self, text, context=None):
        if not text or "@" not in text:
            return text

        def pasted(match):
            role = self.by_glassfrog_id.get(int(match[2]))
            return f"@[{role.name}](role:{role.pk})" if role else match[0]

        text = GLASSFROG_LINK.sub(pasted, text)
        result, position = [], 0
        for match in re.finditer(r"(?<![\w\[])@(?!\[)", text):
            start = match.end()
            if start < position:
                continue
            candidates = self.candidates(text[start : start + 200], context)
            if not candidates:
                self.unresolved.append(text[start : start + 40].split("\n")[0])
                continue
            role, length = candidates[0]
            result.extend((
                text[position : match.start()],
                f"@[{role.name}](role:{role.pk})",
            ))
            position = start + length
        result.append(text[position:])
        return "".join(result)
