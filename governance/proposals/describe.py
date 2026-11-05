"""Readable changes from the instructions of a proposal

Instructions use GlassFrog's JSON-patch-like format, see ``SPEC.md``. The
objects in the paths are resolved with ``Proposal.names`` (their names at
the time of the proposal) and, for links, with the current objects.
"""

import re
from dataclasses import dataclass, field

from django.utils.dateparse import parse_date
from django.utils.formats import date_format
from django.utils.translation import gettext_lazy as _


@dataclass
class Change:
    """One readable change, e.g. an accountability of a role replaced"""

    action: str  # added, changed, removed, moved, elected
    label: str
    subject: str = ""  # The role or policy the change belongs to
    subject_key: str = ""  # e.g. "roles/123", for links
    old: str = ""
    new: str = ""
    details: list = field(default_factory=list)  # (label, text) of additions


FIELD_LABELS = {
    "name": _("Name"),
    "aim": _("Purpose"),
    "purpose": _("Purpose"),
    "title": _("Title"),
    "body": _("Text"),
}


def describe(instructions, names):  # noqa: C901
    """Groups instructions by the role or policy they change"""
    changes = []
    added = {}  # "roles/123" → Change of the addition, collects its fields

    def name(key):
        return names.get(key) or str(_("unknown"))

    for instruction in instructions:
        op = instruction["op"]
        path = instruction["path"]
        value = instruction.get("value")
        original = instruction.get("original_value")
        if op == "test":
            continue

        if match := re.fullmatch(r"/(roles|policies)/(\d+|n\d+)", path):
            key = f"{match[1]}/{match[2]}"
            kind = _("Role") if match[1] == "roles" else _("Policy")
            if op == "add":
                change = Change("added", str(kind), name(key), key)
                added[key] = change
                changes.append(change)
            elif op == "remove":
                changes.append(Change("removed", str(kind), name(key), key))
            elif op == "move":
                source = instruction.get("from", "")
                circle = re.match(r"/circles/(\d+)", source)
                changes.append(
                    Change(
                        "moved",
                        str(kind),
                        name(key),
                        key,
                        old=name(f"circles/{circle[1]}") if circle else "",
                    )
                )
            continue

        if match := re.fullmatch(
            # Also into a circle the proposal creates (n1)
            r"/roles/(\d+|n\d+)/supporting_circle/(roles|policies)/(\d+)",
            path,
        ):
            key = f"{match[2]}/{match[3]}"
            changes.append(
                Change(
                    "moved",
                    str(_("Role") if match[2] == "roles" else _("Policy")),
                    name(key),
                    key,
                    new=name(f"roles/{match[1]}"),
                )
            )
            continue

        if match := re.fullmatch(r"/roles/(\d+|n\d+)/supporting_circle", path):
            key = f"roles/{match[1]}"
            label = (
                _("Turned into a circle")
                if op == "add"
                else _("Turned back into a role")
            )
            if key in added and op == "add":
                added[key].details.append((str(_("Circle")), str(_("yes"))))
            else:
                changes.append(Change("changed", str(label), name(key), key))
            continue

        if match := re.fullmatch(
            r"/(roles|policies)/(\d+|n\d+)/(name|aim|title|body)", path
        ):
            key = f"{match[1]}/{match[2]}"
            label = str(FIELD_LABELS[match[3]])
            if key in added:
                added[key].details.append((label, value or ""))
            else:
                changes.append(
                    Change(
                        "changed",
                        label,
                        name(key),
                        key,
                        old=original or "",
                        new=value or "",
                    )
                )
            continue

        if match := re.fullmatch(
            r"/roles/(\d+|n\d+)/(accountabilities|domains)/(\d+|n\d+)(?:/description)?",
            path,
        ):
            key = f"roles/{match[1]}"
            label = str(
                _("Accountability") if match[2] == "accountabilities" else _("Domain")
            )
            text = (
                value
                if op != "remove"
                else original or names.get(f"{match[2]}/{match[3]}", "")
            )
            if key in added and op == "add":
                added[key].details.append((label, text or ""))
            elif op == "add":
                changes.append(Change("added", label, name(key), key, new=text or ""))
            elif op == "remove":
                changes.append(Change("removed", label, name(key), key, old=text or ""))
            else:
                changes.append(
                    Change(
                        "changed",
                        label,
                        name(key),
                        key,
                        old=original or "",
                        new=value or "",
                    )
                )
            continue

        if match := re.fullmatch(r"/roles/(\d+)/assignment/links/person", path):
            key = f"roles/{match[1]}"
            changes.append(
                Change("elected", str(_("Election")), name(key), key, new=value or "")
            )
            continue

        if match := re.fullmatch(r"/roles/(\d+)/assignment/until", path):
            key = f"roles/{match[1]}"
            election = next(
                (
                    c
                    for c in reversed(changes)
                    if c.action == "elected" and c.subject_key == key
                ),
                None,
            )
            if election and value:
                day = parse_date(value[:10])
                election.details.append((
                    str(_("until")),
                    date_format(day, "SHORT_DATE_FORMAT") if day else value,
                ))
            continue

        if match := re.fullmatch(r"/policies/(\d+)/links/domain", path):
            key = f"policies/{match[1]}"
            changes.append(
                Change(
                    "changed",
                    str(_("Domain")),
                    name(key),
                    key,
                    new=name(f"domains/{value}"),
                )
            )
            continue

        # Anything else is shown as it is
        changes.append(
            Change(
                "changed", path, "", "", old=str(original or ""), new=str(value or "")
            )
        )

    return changes
