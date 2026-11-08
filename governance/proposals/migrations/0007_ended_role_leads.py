from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("proposals", "0006_role_leads_losing_roles"),
    ]

    operations = [
        migrations.RenameField(
            model_name="proposal",
            old_name="ended_holders",
            new_name="ended_role_leads",
        ),
    ]
