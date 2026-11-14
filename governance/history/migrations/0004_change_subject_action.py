from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("history", "0003_links_metrics_checklists"),
    ]

    operations = [
        migrations.AddField(
            model_name="change",
            name="subject",
            field=models.CharField(blank=True, max_length=20, verbose_name="subject"),
        ),
        migrations.AddField(
            model_name="change",
            name="action",
            field=models.CharField(default="", max_length=20, verbose_name="action"),
            preserve_default=False,
        ),
        # ``accountabilities-added`` into subject and action, ``focus`` is the
        # role's (no subject); one pass over the table, not one per kind
        migrations.RunSQL(
            """
            UPDATE history_change SET
                subject = coalesce(substring(kind FROM '^(.*)-[^-]*$'), ''),
                action = substring(kind FROM '([^-]*)$')
            """,
            """
            UPDATE history_change SET kind = CASE
                WHEN subject = '' THEN action ELSE subject || '-' || action END
            """,
        ),
        # Re-added with a default when going back
        migrations.AlterField(
            model_name="change",
            name="kind",
            field=models.CharField(default="", max_length=40, verbose_name="kind"),
        ),
        migrations.RemoveField(model_name="change", name="kind"),
    ]
