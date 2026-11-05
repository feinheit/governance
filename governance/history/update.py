from django.db import transaction

from governance.history.changes import diff_policies, diff_roles
from governance.history.models import Change, Snapshot
from governance.roles.models import Policy, Role


@transaction.atomic
def update_changes(*, since=None):
    """Recomputes the changes between snapshots (from ``since`` on)"""
    snapshots = Snapshot.objects.order_by("date")
    changes = Change.objects.all()
    if since:
        previous = snapshots.filter(date__lt=since).last()
        snapshots = snapshots.filter(date__gte=since)
        changes = changes.filter(date__gte=since)
    else:
        previous = None
    changes.delete()

    roles = set(Role.objects.values_list("pk", flat=True))
    policies = set(Policy.objects.values_list("pk", flat=True))
    new = []
    for snapshot in snapshots.iterator(chunk_size=20):
        if previous is not None:
            for role, kind, old, value in diff_roles(previous.data, snapshot.data):
                if role in roles:
                    new.append(
                        Change(
                            date=snapshot.date,
                            role_id=role,
                            kind=kind,
                            old=old,
                            new=value,
                        )
                    )
            for policy, role, kind, old, value in diff_policies(
                previous.data, snapshot.data
            ):
                if policy in policies:
                    new.append(
                        Change(
                            date=snapshot.date,
                            policy_id=policy,
                            role_id=role if role in roles else None,
                            kind=f"policy-{kind}",
                            old=old,
                            new=value,
                        )
                    )
        previous = snapshot
    Change.objects.bulk_create(new, batch_size=1000)
    return len(new)
