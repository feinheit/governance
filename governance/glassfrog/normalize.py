"""Normalizing GlassFrog's circles snapshots

GlassFrog keeps circle records of roles which were turned back from
circles into roles, and records pointing to roles which don't exist
anymore. A circle is live if its supported role points back to it. Roles
and policies of circles which aren't live are left out. All IDs are
GlassFrog IDs; circles are identified by the ID of their supported role
(circles are roles, see ``SPEC.md``).
"""

from governance.glassfrog.export import without_empty
from governance.roles.constitution import FACILITATOR, LEAD, REP, SECRETARY


CORE_ROLE_NAMES = {
    "lead link": LEAD,
    "circle lead": LEAD,
    "facilitator": FACILITATOR,
    "secretary": SECRETARY,
    "rep link": REP,
    "circle rep": REP,
}


def core_role(role):
    if not role.get("is_core"):
        return ""
    return CORE_ROLE_NAMES.get(role["name"].strip().lower(), "")


def live_circles(circles, roles):
    """GlassFrog circle ID → circle record of the circles which are live"""
    return {
        circle["id"]: circle
        for circle in circles
        if (role := roles.get(circle["links"]["supported_role"]))
        and role["links"].get("supporting_circle") == circle["id"]
    }


def normalize(data):
    """The live structure of a ``circles`` snapshot

    Returns ``{"roles": {id: …}, "policies": {id: …}, "domains": {id: text},
    "people": {id: {"name", "email"}}, "circle_roles": {circle id: role id}}``.
    """
    linked = data.get("linked", {})
    # Until 2019-05 the circles' roles came in a separate list
    roles = {
        role["id"]: role
        for role in without_empty(linked.get("supported_roles"))
        + without_empty(linked.get("roles"))
    }
    circles = live_circles(data.get("circles", []), roles)
    circle_roles = {
        circle_id: circle["links"]["supported_role"]
        for circle_id, circle in circles.items()
    }

    result_roles = {}
    for role_id, role in roles.items():
        links = role["links"]
        circle_id = links.get("circle")
        supporting = links.get("supporting_circle")
        is_circle = supporting in circles and circle_roles[supporting] == role_id
        if circle_id is None:
            if not is_circle:
                continue  # Only the anchor circle has no circle
            parent = None
        elif circle_id in circles:
            parent = circle_roles[circle_id]
        else:
            continue  # In a circle which isn't live

        entry = {
            "name": role["name"],
            "purpose": role.get("purpose") or "",
            "circle": parent,
            "is_circle": is_circle,
            "core_role": core_role(role),
            "accountabilities": list(links.get("accountabilities") or []),
            "domains": list(links.get("domains") or []),
            "people": list(links.get("people") or []),
            "elected_until": role.get("elected_until"),
        }
        if is_circle:
            circle = circles[supporting]
            entry |= {
                "circle_id": supporting,
                "short_name": circle.get("short_name") or "",
                "strategy": circle.get("strategy") or "",
            }
        result_roles[role_id] = entry

    # Drop roles whose chain of circles doesn't reach the anchor circle
    def reaches_anchor(role_id, seen=()):
        entry = result_roles.get(role_id)
        if entry is None or role_id in seen:
            return False
        if entry["circle"] is None:
            return True
        return reaches_anchor(entry["circle"], (*seen, role_id))

    result_roles = {
        role_id: entry
        for role_id, entry in result_roles.items()
        if reaches_anchor(role_id)
    }

    # Circles with only their core roles are roles (the app turns circles
    # without roles of their own back into roles automatically; GlassFrog
    # left some behind). Not the anchor circle.
    for role_id, entry in list(result_roles.items()):
        if not entry["is_circle"] or entry["circle"] is None:
            continue
        children = [r for r in result_roles.values() if r["circle"] == role_id]
        if all(child["core_role"] for child in children):
            entry["is_circle"] = False
            for key in ["circle_id", "short_name", "strategy"]:
                entry.pop(key, None)
            result_roles = {
                child_id: child
                for child_id, child in result_roles.items()
                if child["circle"] != role_id
            }

    policies = {}
    for policy in without_empty(linked.get("policies")):
        links = policy.get("links", {})
        # Early snapshots use circle_id and role_id
        owner = (links.get("role") or links.get("role_id")) or circle_roles.get(
            links.get("circle") or links.get("circle_id")
        )
        if owner in result_roles:
            policies[policy["id"]] = {
                "title": policy.get("title") or "",
                "body": policy.get("body") or "",
                "role": owner,
                "domain": links.get("domain"),
            }

    return {
        "roles": result_roles,
        "policies": policies,
        "domains": {
            domain["id"]: domain.get("description") or ""
            for domain in without_empty(linked.get("domains"))
        },
        "people": {
            person["id"]: {
                "name": person.get("name") or "",
                "email": person.get("email") or "",
            }
            for person in without_empty(linked.get("people"))
        },
        "circle_roles": circle_roles,
        # Short names of all circle records, also stale ones: texts use them
        "short_names": {
            circle["links"]["supported_role"]: circle.get("short_name") or ""
            for circle in data.get("circles", [])
        },
    }
