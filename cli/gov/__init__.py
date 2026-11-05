"""The Governance CLI, `gov <noun> <verb>`"""

from gov import (  # noqa: F401 Register the commands
    auth,
    circles,
    domains,
    policies,
    proposals,
    roles,
    search,
)
from gov.core import cli


__all__ = ["cli"]
