"""Mentions of roles in texts: ``@[Name](role:123)``

Texts mention roles by their ID so that renaming a role updates them; they
are rendered as links with the current name (the GlassFrog import converted
GlassFrog's plain text mentions). Texts written without picking the role
from the autocomplete (``mentions.js``) mention it as "@Name": saving them
turns these into mentions (``link_mentions()``).
"""

import re

from django.urls import reverse


MENTION = re.compile(r"@\[([^\]]*)\]\(role:(\d+)\)")
# An "@" which may start a role's name: not in an email address or a word,
# not a mention or a link's text already
PLAIN = re.compile(r"(?<![\w@\[])@(?!\[)")


def link_mentions(text):
    """``@Name`` as ``@[Name](role:ID)`` where exactly one active role has
    the name (ignoring case, the longest name wins, "@Circle Lead" stays
    plain because every circle has one)"""
    from governance.roles.models import Role

    if not text or not PLAIN.search(text):
        return text
    roles = {}
    for pk, name in Role.objects.active().values_list("pk", "name"):
        key = name.strip().casefold()
        if key:
            roles[key] = None if key in roles else (pk, name.strip())
    names = sorted(
        ((key, role) for key, role in roles.items() if role),
        key=lambda item: -len(item[0]),
    )

    result, position = [], 0
    for match in PLAIN.finditer(text):
        start = match.end()
        if start < position:
            continue
        for key, (pk, name) in names:
            end = start + len(name)
            if text[start:end].casefold() == key and not (
                end < len(text) and (text[end].isalnum() or text[end] == "_")
            ):
                result.append(f"{text[position : match.start()]}@[{name}](role:{pk})")
                position = end
                break
    return "".join(result) + text[position:]


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


def link_mentions_of(instance, fields, kwargs):
    """``link_mentions()`` in the instance's fields which ``save()`` writes"""
    update_fields = kwargs.get("update_fields")
    for field in fields:
        if update_fields is None or field in update_fields:
            setattr(instance, field, link_mentions(getattr(instance, field)))


# Texts of proposals' instructions, not names and titles
TEXT_PATH = re.compile(
    r".*/(?:aim|description|body|(?:accountabilities|domains)/[^/]+)"
)


def link_mentions_in_instructions(instructions):
    return [
        {**instruction, "value": link_mentions(instruction["value"])}
        if isinstance(instruction.get("value"), str)
        and TEXT_PATH.fullmatch(instruction["path"])
        else instruction
        for instruction in instructions
    ]
