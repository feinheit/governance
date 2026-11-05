from django.db import migrations


def audit_tables(*tables, exclude=()):
    """The audit trigger (audit.sql) on the tables, without the excluded
    columns; for the apps' migrations"""
    excluded = f", ARRAY[{', '.join(repr(c) for c in exclude)}]" if exclude else ""
    return migrations.RunSQL(
        "".join(f"SELECT audit_audit_table('{table}'{excluded});" for table in tables),
        reverse_sql="".join(
            f"DROP TRIGGER IF EXISTS audit_trigger_row ON {table};"
            f"DROP TRIGGER IF EXISTS audit_trigger_stm ON {table};"
            for table in tables
        ),
    )
