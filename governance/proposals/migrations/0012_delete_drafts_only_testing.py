from django.db import migrations


def delete_drafts_only_testing(apps, schema_editor):
    """Drafts without a tension whose instructions only check that a role
    exists (``test``, started in GlassFrog): empty like those 0011 deleted"""
    Proposal = apps.get_model("proposals", "Proposal")
    drafts = (
        Proposal.objects
        .filter(status="draft", tension__regex=r"^\s*$")
        .exclude(instructions=[])
        .exclude(responses__isnull=False)
        .exclude(agenda_items__meeting__ended_at=None, agenda_items__isnull=False)
    )
    Proposal.objects.filter(
        pk__in=[
            draft.pk
            for draft in drafts
            if all(i.get("op") == "test" for i in draft.instructions)
        ]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("proposals", "0011_delete_empty_drafts"),
    ]

    operations = [
        migrations.RunPython(delete_drafts_only_testing, migrations.RunPython.noop),
    ]
