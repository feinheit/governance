from django.db import migrations


def delete_empty(apps, schema_editor):
    """Proposals without a tension and without changes (e.g. "New proposal"
    left without saving anything) have nothing to keep; not those an agenda
    item or a response refers to"""
    Proposal = apps.get_model("proposals", "Proposal")
    Proposal.objects.filter(tension__regex=r"^\s*$", instructions=[]).exclude(
        responses__isnull=False
    ).exclude(agenda_items__isnull=False).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("proposals", "0007_ended_role_leads"),
        ("meetings", "0007_election_nobody"),
    ]

    operations = [
        migrations.RunPython(delete_empty, migrations.RunPython.noop),
    ]
