from django.db import migrations, models


def mark(apps, schema_editor):
    """After the last import: adopted imported proposals without a role were
    adopted in GlassFrog (the import sets no role, meetings here do)"""
    Proposal = apps.get_model("proposals", "Proposal")
    Proposal.objects.filter(
        glassfrog_id__isnull=False, status="adopted", role__isnull=True
    ).update(adopted_in_glassfrog=True)


class Migration(migrations.Migration):
    dependencies = [
        ("proposals", "0003_ended_holders"),
    ]

    operations = [
        migrations.AddField(
            model_name="proposal",
            name="adopted_in_glassfrog",
            field=models.BooleanField(
                default=False,
                help_text="Its instructions refer to GlassFrog's IDs.",
                verbose_name="adopted in GlassFrog",
            ),
        ),
        migrations.RunPython(mark, migrations.RunPython.noop),
    ]
