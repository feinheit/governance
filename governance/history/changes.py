"""Differences between the structures of two days, see ``history.audit``"""

from collections import Counter


def _texts(texts):
    """Known texts and the number of texts which weren't recorded"""
    known = Counter(text for text in texts if text is not None)
    return known, sum(1 for text in texts if text is None)


def diff_roles(old, new):
    """Yields ``(role, kind, old, new)`` for the differences of two snapshots"""
    old_roles, new_roles = old.get("roles", {}), new.get("roles", {})
    for pk in new_roles.keys() - old_roles.keys():
        yield int(pk), "added", "", new_roles[pk]["name"]
    for pk in old_roles.keys() - new_roles.keys():
        yield int(pk), "removed", old_roles[pk]["name"], ""
    for pk in new_roles.keys() & old_roles.keys():
        a, b = old_roles[pk], new_roles[pk]
        for field in ["name", "purpose", "strategy"]:
            if (a.get(field) or "") != (b.get(field) or ""):
                yield int(pk), field, a.get(field) or "", b.get(field) or ""
        if a["circle"] != b["circle"]:
            yield int(pk), "moved", a["circle"], b["circle"]
        if a["is_circle"] != b["is_circle"]:
            yield int(pk), "circle" if b["is_circle"] else "role", "", ""
        for field in ["accountabilities", "domains"]:
            (a_known, a_unknown), (b_known, b_unknown) = (
                _texts(a[field]),
                _texts(b[field]),
            )
            for text in (a_known - b_known).elements():
                yield int(pk), f"{field}-removed", text, ""
            for text in (b_known - a_known).elements():
                yield int(pk), f"{field}-added", "", text
            if a_unknown != b_unknown or (
                (a_unknown or b_unknown) and len(a[field]) != len(b[field])
            ):
                yield int(pk), f"{field}-unrecorded", a_unknown, b_unknown
        a_users = {x["user"] for x in a["assignments"]}
        b_users = {x["user"] for x in b["assignments"]}
        for user in b_users - a_users:
            yield int(pk), "assigned", "", user
        for user in a_users - b_users:
            yield int(pk), "unassigned", user, ""


def diff_policies(old, new):
    """Yields ``(policy, role, kind, old, new)``"""
    old_policies, new_policies = old.get("policies", {}), new.get("policies", {})
    for pk in new_policies.keys() - old_policies.keys():
        yield int(pk), new_policies[pk]["role"], "added", "", new_policies[pk]["title"]
    for pk in old_policies.keys() - new_policies.keys():
        yield (
            int(pk),
            old_policies[pk]["role"],
            "removed",
            old_policies[pk]["title"],
            "",
        )
    for pk in new_policies.keys() & old_policies.keys():
        a, b = old_policies[pk], new_policies[pk]
        for field in ["title", "body"]:
            if a[field] != b[field]:
                yield int(pk), b["role"], field, a[field], b[field]
        if a["role"] != b["role"]:
            yield int(pk), b["role"], "moved", a["role"], b["role"]
        elif a.get("domain") and b.get("domain") and a["domain"] != b["domain"]:
            # Another domain, not a domain renamed (days of GlassFrog
            # without the domain's ID in the app don't count)
            yield int(pk), b["role"], "domain", a["domain_text"], b["domain_text"]
