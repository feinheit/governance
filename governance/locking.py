"""One change of the structure after the other"""

from functools import wraps

from django.db import connection


# pg_advisory_xact_lock()'s key of lock_structure(), any number of our own
STRUCTURE_LOCK = 20261107


def lock_structure():
    """One change of the structure after the other, until the transaction
    ends: two proposals adopted at once (a meeting and the nightly task,
    two requests) check against each other's changes, e.g. one moving a role
    into a circle whose last role the other removes. Adopting is rare,
    waiting a moment doesn't matter."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [STRUCTURE_LOCK])


def locking_structure(view):
    """Views changing assignments, domain policies and elections around the
    process: their POSTs wait for adoptions running at the same moment and
    load everything afterwards (the lock holds until the request's
    transaction ends, ``ATOMIC_REQUESTS``), their checks see the result"""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if request.method == "POST":
            lock_structure()
        return view(request, *args, **kwargs)

    return wrapper
