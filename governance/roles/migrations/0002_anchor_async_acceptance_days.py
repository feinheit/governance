from django.db import migrations


def forwards(apps, schema_editor):
    """GlassFrog has no setting for it, only a policy: the default on the
    anchor circle, the sub-circles inherit it (like the import does)"""
    apps.get_model("roles", "Role").objects.filter(
        circle=None,
        is_circle=True,
        archived_on=None,
        async_acceptance_days=None,
    ).update(async_acceptance_days=4)


class Migration(migrations.Migration):
    dependencies = [("roles", "0001_initial")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
