import re

from django.db import migrations
from django.utils.text import Truncator


MENTION = re.compile(r"@\[([^\]]*)\]\(role:(\d+)\)")


def drafts_into_inboxes(apps, schema_editor):
    """Drafts without changes were tensions only their proposer saw: they're
    private tensions in their circle's inbox now (decided 2026-11-25), or go
    back to the tension they were drafted from. Not those on an agenda (the
    item would lose its link), without a proposer or outside an active
    circle (roles' inner circles have no inbox)"""
    Proposal = apps.get_model("proposals", "Proposal")
    Tension = apps.get_model("meetings", "Tension")
    Role = apps.get_model("roles", "Role")
    drafts = (
        Proposal.objects
        .filter(
            status="draft",
            proposer__isnull=False,
            circle__is_circle=True,
            circle__archived_on=None,
        )
        .exclude(tension__regex=r"^\s*$")
        .exclude(agenda_items__isnull=False)
        .exclude(responses__isnull=False)
        .order_by("created_at", "pk")
    )
    for draft in drafts:
        if any(i.get("op") != "test" for i in draft.instructions):
            continue
        if source := Tension.objects.filter(proposal=draft).first():
            source.proposal = None
            source.save(update_fields=["proposal"])
        else:
            text = draft.tension.strip()
            lines = [line.strip() for line in text.splitlines()]
            first = next((li for li in lines if li and not li.startswith("#")), "")
            ids = {int(match[2]) for match in MENTION.finditer(first)}
            names = dict(Role.objects.filter(pk__in=ids).values_list("pk", "name"))
            title = MENTION.sub(
                lambda match, names=names: f"@{names.get(int(match[2]), match[1])}",
                first,
            )
            tension = Tension.objects.create(
                circle=draft.circle,
                owner=draft.proposer,
                title=Truncator(title).chars(100),
                description="" if text == first else text,
                is_private=True,
            )
            # Noted then, not now (``auto_now_add``)
            Tension.objects.filter(pk=tension.pk).update(created_at=draft.created_at)
        draft.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("meetings", "0008_tensions"),
    ]

    operations = [
        migrations.RunPython(drafts_into_inboxes, migrations.RunPython.noop),
    ]
