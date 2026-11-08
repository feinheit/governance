from django.db import migrations


def update_changes(apps, schema_editor):
    """The changes again, now with the links, metrics and checklist items
    (the audit log has them since the beginning)"""
    from governance.history.update import update_changes

    update_changes()


class Migration(migrations.Migration):
    dependencies = [
        # update_changes() of today reads all of these
        ("history", "0002_delete_snapshot"),
        ("audit", "0001_initial"),
        ("accounts", "0001_initial"),
        ("meetings", "0006_election_undo"),
        ("proposals", "0003_ended_holders"),
        ("roles", "0003_one_assignment_per_role_and_user"),
    ]

    operations = [migrations.RunPython(update_changes, migrations.RunPython.noop)]
