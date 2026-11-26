"""Mentions of roles in texts: ``@[Name](role:123)``

Texts mention roles by their ID so that renaming a role updates them; they
are rendered as links with the current name (the GlassFrog import converted
GlassFrog's plain text mentions). Texts written without picking the role
from the autocomplete (``mentions.js``) mention it as "@Name": saving them
turns these into mentions (``link_mentions()``).
"""

import re
from collections import defaultdict

from django.urls import reverse


MENTION = re.compile(r"@\[([^\]]*)\]\(role:(\d+)\)")
# An "@" which may start a role's name: not in an email address or a word,
# not a mention or a link's text already
PLAIN = re.compile(r"(?<![\w@\[])@(?!\[)")


def link_mentions(text, circle_id=None):
    """``@Name`` as ``@[Name](role:ID)`` where exactly one active role has
    the name, or else exactly one of the circle's roles (ignoring case, the
    longest name wins: "@Facilitator" is the circle's, other circles have
    one too)"""
    from governance.roles.models import Role

    if not text or not PLAIN.search(text):
        return text
    candidates = defaultdict(list)
    for pk, name, circle in Role.objects.active().values_list("pk", "name", "circle"):
        if key := name.strip().casefold():
            candidates[key].append((pk, name.strip(), circle))
    names = []
    for key, roles in candidates.items():
        found = (
            roles
            if len(roles) == 1
            else [role for role in roles if circle_id and role[2] == circle_id]
        )
        if len(found) == 1:
            names.append((key, found[0][:2]))
    names.sort(key=lambda item: -len(item[0]))

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


def link_mentions_of(instance, fields, kwargs, circle_id):
    """``link_mentions()`` in the instance's fields which ``save()`` writes"""
    update_fields = kwargs.get("update_fields")
    for field in fields:
        if update_fields is None or field in update_fields:
            text = link_mentions(getattr(instance, field), circle_id)
            setattr(instance, field, text)


# Texts of proposals' instructions, not names and titles
TEXT_PATH = re.compile(
    r".*/(?:aim|description|body|(?:accountabilities|domains)/[^/]+)"
)


def link_mentions_in_instructions(instructions, circle_id):
    return [
        {**instruction, "value": link_mentions(instruction["value"], circle_id)}
        if isinstance(instruction.get("value"), str)
        and TEXT_PATH.fullmatch(instruction["path"])
        else instruction
        for instruction in instructions
    ]
