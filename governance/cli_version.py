"""Telling users of the gov command line interface (cli/) to upgrade"""

import tomllib

from django.conf import settings
from django.http import JsonResponse
from django.utils.translation import gettext as _


# Raise this when the API changes in ways older CLIs cannot handle
MINIMUM = (0, 13, 0)
# Where gov is installed from
INSTALL = "git+https://github.com/feinheit/governance#subdirectory=cli"
_PROJECT = tomllib.loads((settings.BASE_DIR / "cli" / "pyproject.toml").read_text())[
    "project"
]
# The version in the repository, users of older versions are told to upgrade
LATEST = _PROJECT["version"]
# uv tool upgrade keeps the tool's Python and fails when the CLI requires a
# newer one, --python switches to it
PYTHON = _PROJECT["requires-python"].removeprefix(">=")
UPGRADE = f"uv tool upgrade --python {PYTHON} governance-cli"


def _parse(version):
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError:
        return ()


def cli_version_middleware(get_response):
    """Reject CLIs which are too old, tell outdated ones about the latest
    version"""

    def middleware(request):
        if not (version := request.headers.get("X-Governance-CLI")):
            return get_response(request)
        if _parse(version) < MINIMUM:
            return JsonResponse(
                {
                    "detail": _("Your gov is too old, please upgrade it: %(command)s")
                    % {"command": UPGRADE}
                },
                status=426,
            )
        response = get_response(request)
        response["X-Governance-CLI-Latest"] = LATEST
        response["X-Governance-CLI-Upgrade"] = UPGRADE
        return response

    return middleware
