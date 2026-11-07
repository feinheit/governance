"""The core roles of the Holacracy Constitution 5.0

Their purposes, accountabilities and domains come from the constitution,
not from data, and can't be changed through governance (a circle may add
accountabilities and domains). The texts are the ones GlassFrog shows, see
``docs/constitution/``. The Circle Lead holds the purpose of the circle.
"""

from dataclasses import dataclass, field

from django.utils.translation import gettext_lazy as _


LEAD = "lead"
FACILITATOR = "facilitator"
SECRETARY = "secretary"
REP = "rep"


@dataclass(frozen=True)
class CoreRole:
    key: str
    name: str
    purpose: str = ""
    accountabilities: list = field(default_factory=list)
    domains: list = field(default_factory=list)
    is_elected: bool = True


CORE_ROLES = {
    role.key: role
    for role in [
        CoreRole(LEAD, _("Circle Lead"), is_elected=False),
        CoreRole(
            FACILITATOR,
            _("Facilitator"),
            _(
                "Circle governance and operational practices aligned with the Constitution."
            ),
            [
                _("Facilitating the Circle’s Governance Process"),
                _("Facilitating the Circle’s regular Tactical Meetings"),
                _(
                    "Auditing a Sub-Circle’s meetings and records on request and"
                    " declaring a Process Breakdown if one is discovered"
                ),
                _(
                    "Triggering new elections for the Circle’s elected Roles after each election term expires"
                ),
            ],
        ),
        CoreRole(
            SECRETARY,
            _("Secretary"),
            _("Stabilize the Circle’s constitutionally-required records and meetings."),
            [
                _("Scheduling Governance Meetings for the Circle"),
                _("Scheduling regular Tactical Meetings for the Circle"),
                _(
                    "Capturing and publishing the outputs of the Circle’s Governance Process"
                ),
                _("Capturing and publishing Tactical Meeting outputs"),
                _(
                    "Interpreting the Constitution and anything under its authority upon request"
                ),
            ],
            [_("All governance records of the Circle")],
        ),
        CoreRole(
            REP,
            _("Circle Rep"),
            _(
                "Tensions relevant to process in a broader Circle channeled out and resolved."
            ),
            [
                _(
                    "Seeking to understand Tensions conveyed by Role Leads within the Circle"
                ),
                _(
                    "Discerning Tensions appropriate to process within a broader Circle that holds the Circle"
                ),
                _(
                    "Processing Tensions within a broader Circle to remove constraints on the Circle"
                ),
            ],
        ),
    ]
}

CORE_ROLE_CHOICES = [(role.key, role.name) for role in CORE_ROLES.values()]


def constitutional_texts():
    """All constitutional accountabilities and domains, also in English

    The history's backfill uses them to skip the core roles'
    constitutional accountabilities stored in GlassFrog's data.
    """
    from django.utils.translation import override

    texts = set()
    for language in ["en", "de"]:
        with override(language):
            for role in CORE_ROLES.values():
                texts.update(str(text) for text in role.accountabilities + role.domains)
    return texts
