from pathlib import Path

import django.contrib.postgres.fields.hstore
from django.contrib.postgres.operations import HStoreExtension, UnaccentExtension
from django.db import migrations, models


AUDIT_SQL = (Path(__file__).parent.parent / "audit.sql").read_text(encoding="utf-8")


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        HStoreExtension(),
        UnaccentExtension(),
        migrations.RunSQL(AUDIT_SQL, reverse_sql=migrations.RunSQL.noop),
        migrations.CreateModel(
            name="LoggedAction",
            fields=[
                ("event_id", models.IntegerField(primary_key=True, serialize=False)),
                ("table_name", models.TextField()),
                ("user_name", models.TextField(null=True)),
                ("created_at", models.DateTimeField()),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("I", "INSERT"),
                            ("U", "UPDATE"),
                            ("D", "DELETE"),
                            ("T", "TRUNCATE"),
                        ],
                        max_length=1,
                    ),
                ),
                (
                    "row_data",
                    django.contrib.postgres.fields.hstore.HStoreField(null=True),
                ),
                (
                    "changed_fields",
                    django.contrib.postgres.fields.hstore.HStoreField(null=True),
                ),
            ],
            options={
                "verbose_name": "logged action",
                "verbose_name_plural": "logged actions",
                "db_table": "audit_logged_actions",
                "ordering": ["event_id"],
                "managed": False,
            },
        ),
    ]
