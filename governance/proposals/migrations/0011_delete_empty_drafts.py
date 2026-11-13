from django.db import migrations


def delete_empty_drafts(apps, schema_editor):
    """Empty drafts on the agenda of ended meetings too (e.g. GlassFrog's
    for elections): the items keep their labels, only the link to a draft
    nobody else sees goes; adopted ones stay, they're history"""
    Proposal = apps.get_model("proposals", "Proposal")
    Proposal.objects.filter(
        status="draft", tension__regex=r"^\s*$", instructions=[]
    ).exclude(responses__isnull=False).exclude(
        agenda_items__meeting__ended_at=None, agenda_items__isnull=False
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("proposals", "0010_conflicting"),
    ]

    operations = [
        migrations.RunPython(delete_empty_drafts, migrations.RunPython.noop),
    ]
