"""The Governance CLI"""

import csv
import datetime as dt
import json
import os
import platform
import secrets
import shlex
import socket
import sys
import tempfile
import threading
import time
import tomllib
import traceback
import webbrowser
from functools import cache
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib.metadata import version
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

import click
import requests
import tomli_w
import yaml
from click.shell_completion import CompletionItem
from rich import box
from rich.console import Console
from rich.style import Style
from rich.table import Table
from rich.text import Text


CONFIG = Path.home() / ".config" / "governance.toml"


BUG_REPORTS = Path.home() / ".cache" / "gov"


CACHE = Path.home() / ".cache" / "gov"


# Short names and teams for completing options change rarely
COMPLETION_TTL = 24 * 60 * 60


def _version():
    """The version of the checkout for editable installs, their metadata
    keeps the version they were installed with"""
    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    if pyproject.exists():
        return tomllib.loads(pyproject.read_text())["project"]["version"]
    return version("governance-cli")


VERSION = _version()


console = Console(markup=False, highlight=False)


def terminate(msg):
    click.echo(msg, file=sys.stderr)
    sys.exit(1)


class _ServerError(Exception):
    """Governance failed, the bug report contains the request and the response"""

    def __init__(self, status_code, details):
        super().__init__(status_code)
        self.status_code = status_code
        self.details = details


def _bug_report(problem, details, *, args):
    """Write what's needed to fix a bug into a file people can send"""
    try:
        url = (
            installation_url(os.environ.get("GOVERNANCE_URL"))
            or read_config()["current"]
        )
    except Exception:  # noqa: BLE001
        url = None
    now = dt.datetime.now().astimezone()
    report = "\n".join([
        f"gov {VERSION}, Python {platform.python_version()} on {platform.platform()}",
        f"Installation: {url or 'unknown'}",
        f"Command: {shlex.join(['gov', *args])}",
        f"Time: {now.isoformat(timespec='seconds')}",
        "",
        details,
    ])
    path = BUG_REPORTS / f"bug-report-{now:%Y%m%d-%H%M%S}.txt"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report)
    except OSError:
        terminate(
            f"{problem} Please send this to the people running Governance:\n\n{report}"
        )
    terminate(
        f"{problem} Please send {path} to the people running Governance"
        " and tell them what you tried to do."
    )


class _Group(click.Group):
    """Commands which crash write a bug report instead of a traceback, set
    GOV_DEBUG to get the exception

    ``aliases`` maps short names to commands, the help lists them
    separately."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.aliases = {}

    def get_command(self, ctx, cmd_name):
        return super().get_command(ctx, self.aliases.get(cmd_name, cmd_name))

    def resolve_command(self, ctx, args):
        # Show the full name in usage and error messages
        _name, command, args = super().resolve_command(ctx, args)
        return command.name if command else None, command, args

    def format_commands(self, ctx, formatter):
        super().format_commands(ctx, formatter)
        if self.aliases:
            with formatter.section("Aliases"):
                formatter.write_dl(sorted(self.aliases.items()))

    def main(self, args=None, **kwargs):
        args = sys.argv[1:] if args is None else list(args)
        try:
            return super().main(args, **kwargs)
        except Exception as exc:
            if os.environ.get("GOV_DEBUG"):
                raise
            if isinstance(exc, _ServerError):
                _bug_report(
                    f"Governance failed ({exc.status_code}).", exc.details, args=args
                )
            _bug_report(
                f"gov crashed ({type(exc).__name__}: {exc}).",
                traceback.format_exc(),
                args=args,
            )


def read_config():
    """The current installation's URL and the tokens of all installations"""
    config = tomllib.loads(CONFIG.read_text()) if CONFIG.exists() else {}
    return {
        "current": installation_url(config.get("current")),
        "installations": {
            installation_url(url): installation
            for url, installation in config.get("installations", {}).items()
        },
    }


def installation_url(url):
    """The scheme and the host which identify an installation, URLs may be
    pasted from the browser"""
    if not url:
        return url
    if "://" not in url:
        url = f"https://{url}"
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc.lower()}"


def write_config(config):
    """TOML has no null, leave out empty values"""
    data = {"current": config["current"]} if config["current"] else {}
    data["installations"] = {
        url: {key: value for key, value in installation.items() if value}
        for url, installation in sorted(config["installations"].items())
    }
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    # mkstemp creates the file readable by its owner only. Replacing the
    # configuration with it means nobody ever sees a half-written file.
    fd, path = tempfile.mkstemp(
        dir=CONFIG.parent, prefix=f".{CONFIG.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(tomli_w.dumps(data))
        os.replace(path, CONFIG)
    except BaseException:
        Path(path).unlink(missing_ok=True)
        raise


def save_config(url, token, access=None):
    """Store the token of the installation and make it the current one

    The access is remembered to ask for the same access when the token
    expires; it is unknown for pasted tokens."""
    config = read_config()
    # Keep the other settings of the installation, but not the access of
    # the old token
    previous = config["installations"].get(url, {})
    config["installations"][url] = (
        {key: value for key, value in previous.items() if key != "access"}
        | {"token": token}
        | ({"access": access} if access else {})
    )
    config["current"] = url
    write_config(config)


# The installation selected with --installation for this invocation, and
# whether gov already said which installation it uses
_selected_installation = None
_announced = False


def current_installation():
    """The URL of the installation commands talk to: --installation, then
    GOVERNANCE_URL (e.g. for one terminal), then the current one"""
    return (
        _selected_installation
        or installation_url(os.environ.get("GOVERNANCE_URL"))
        or read_config()["current"]
    )


def find_installation(name):
    """The URL of the installation NAME is a unique part of"""
    urls = sorted(read_config()["installations"])
    matches = [url for url in urls if url == name] or [
        url for url in urls if name in url
    ]
    if len(matches) != 1:
        terminate(
            f"{'Several' if matches else 'No'} installations match {name!r}:"
            f" {', '.join(matches or urls) or '(none)'}. Add new ones with"
            " `gov login URL`."
        )
    return matches[0]


def complete_installations(ctx, param, incomplete):
    # Host names only: bash splits words at the colon of https://
    return [
        CompletionItem(host)
        for host in sorted(
            urlsplit(url).netloc for url in read_config()["installations"]
        )
        if incomplete in host
    ]


def completion(name, path, extract, *, ttl=COMPLETION_TTL):
    """Complete IDs with the names as descriptions, fetched from the API at
    most every ``ttl`` seconds per installation; nothing if anything fails

    ``extract`` turns the response into ``(id, description)`` pairs. Typing
    a part of the name also works, the shell replaces it with the ID."""

    def values():
        url = current_installation()
        token = read_config()["installations"].get(url, {}).get("token")
        if not url or not token:
            return []
        cache = CACHE / f"completion-{urlsplit(url).netloc}-{name}.json"
        try:
            if time.time() - cache.stat().st_mtime < ttl:
                return json.loads(cache.read_text())
        except OSError, ValueError:
            pass
        try:
            response = requests.request(
                "GET",
                urljoin(url, f"/api/{path}"),
                headers={
                    "authorization": f"Bearer {token}",
                    "x-governance-cli": VERSION,
                },
                timeout=5,
            )
            items = [[str(id), str(help)] for id, help in extract(response.json())]
        except requests.RequestException, ValueError, KeyError, TypeError:
            return []
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(items))
        return items

    def complete(ctx, param, incomplete):
        text = incomplete.casefold()
        return [
            CompletionItem(id, help=help)
            for id, help in values()
            if id.startswith(incomplete) or (text and text in help.casefold())
        ]

    return complete


def _with_circle(name, circle):
    return f"{name} ({circle})" if circle else name


complete_circles = completion(
    "circles", "circles/", lambda data: [(c["id"], c["name"]) for c in data]
)
complete_roles = completion(
    "roles",
    "roles/",
    lambda data: [(r["id"], _with_circle(r["name"], r["circle"])) for r in data],
)
# One's own roles change more often than the structure
complete_my_roles = completion(
    "my-roles",
    "me/",
    lambda data: [
        (r["id"], _with_circle(r["name"], r["circle"])) for r in data["roles"]
    ],
    ttl=60 * 60,
)
complete_policies = completion(
    "policies",
    "policies/",
    lambda data: [(p["id"], _with_circle(p["title"], p["role"])) for p in data],
)
complete_proposals = completion(
    "proposals",
    "proposals/",
    lambda data: [(p["id"], f"{p['title']} ({p['status']})") for p in data],
    ttl=5 * 60,
)


def _select_installation(ctx, param, value):
    global _selected_installation, _announced  # noqa: PLW0603
    _selected_installation = find_installation(value) if value else None
    _announced = False


def announce_installation(url):
    """Say once when a command doesn't use the current installation, on
    stderr to keep the output clean"""
    global _announced  # noqa: PLW0603
    current = read_config()["current"]
    if _announced or not current or url == current:
        return
    _announced = True
    source = "--installation" if _selected_installation else "GOVERNANCE_URL"
    click.secho(
        f"Using {url} ({source}), not the current {current}.", fg="yellow", err=True
    )


def _config():
    """URL and token of the current installation

    GOVERNANCE_URL selects another installation gov is logged in to, e.g. for
    the commands of one terminal."""
    url = current_installation()
    token = read_config()["installations"].get(url, {}).get("token")
    if not url or not token:
        terminate("Not configured yet. Run `gov login URL` first.")
    announce_installation(url)
    return url, token


def _can_login_again(url):
    """The access to ask for again when the token expires, if any

    Expired tokens are replaced through the browser, but only for people
    sitting in front of a terminal and only with the same access as before."""
    if not sys.stdin.isatty():
        return None
    return read_config()["installations"].get(url, {}).get("access")


LOGIN_TIMEOUT = 300


def browser_login(url, access):
    """Authorize gov in the browser and store the token

    Governance posts the token to a server listening on a local port, the
    state protects against tokens posted by others."""
    state = secrets.token_urlsafe(24)
    result = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("content-length", 0))
            data = parse_qs(self.rfile.read(length).decode())
            if data.get("state") != [state] or not data.get("token"):
                self.send_error(400)
                return
            result["token"] = data["token"][0]
            body = b"gov is authorized. You can close this window."
            self.send_response(200)
            self.send_header("content-type", "text/plain; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = 1
    login_url = (
        urljoin(url, "/cli-login/")
        + "?"
        + urlencode({
            "port": server.server_address[1],
            "state": state,
            "name": socket.gethostname(),
            "access": access,
        })
    )
    click.echo(f"Authorize gov in your browser: {login_url}", err=True)
    # webbrowser waits for some browser commands to exit, serve meanwhile
    threading.Thread(target=webbrowser.open, args=[login_url], daemon=True).start()
    deadline = time.monotonic() + LOGIN_TIMEOUT
    with server:
        while "token" not in result and time.monotonic() < deadline:
            server.handle_request()
    if "token" not in result:
        terminate("Timed out waiting for the browser.")
    save_config(url, result["token"], access)
    click.echo(f"Saved {CONFIG}", err=True)
    return result["token"]


def _parse_version(version):
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError:
        return ()


@cache
def _check_version(latest, upgrade):
    """Tell the user about a newer version, or that the Governance is older
    than the CLI and may not support everything yet, once

    ``latest`` is the version of the CLI in the Governance checkout,
    ``upgrade`` the command which upgrades to it (it may need a newer
    Python)."""
    if not latest:
        return
    if _parse_version(latest) > _parse_version(VERSION):
        upgrade = upgrade or "uv tool upgrade governance-cli"
        click.secho(
            f"gov {latest} is available (you have {VERSION}): {upgrade}",
            fg="yellow",
            err=True,
        )
    elif _parse_version(latest) < _parse_version(VERSION):
        click.secho(
            f"This Governance is older than your gov ({latest} < {VERSION}),"
            " some commands may fail until it is updated.",
            fg="yellow",
            err=True,
        )


def format_error(error):
    """A validation error, prefixed with the field if there is one"""
    if loc := ".".join(str(part) for part in error["loc"][2:]):
        return f"{loc}: {error['msg']}"
    return error["msg"]


def _send(method, url, path, token, **kwargs):
    try:
        return requests.request(
            method,
            urljoin(url, f"/api/{path}"),
            headers={"authorization": f"Bearer {token}", "x-governance-cli": VERSION},
            timeout=30,
            **kwargs,
        )
    except requests.RequestException as exc:
        terminate(str(exc))


def request(method, path, **kwargs):
    """Request the API, terminate on errors

    Expired tokens are replaced and the request is sent again."""
    url, token = _config()
    response = _send(method, url, path, token, **kwargs)
    if response.status_code == 401 and (access := _can_login_again(url)):
        click.secho("Your access has expired.", fg="yellow", err=True)
        token = browser_login(url, access)
        response = _send(method, url, path, token, **kwargs)
    _check_version(
        response.headers.get("x-governance-cli-latest"),
        response.headers.get("x-governance-cli-upgrade"),
    )
    if response.status_code == 401:
        terminate("Not authorized (anymore). Run `gov login` to log in again.")
    if response.status_code == 422:
        terminate("\n".join(format_error(error) for error in response.json()["detail"]))
    if response.status_code >= 500:
        raise _ServerError(
            response.status_code,
            f"{method} {path} {kwargs.get('params') or ''}\n"
            f"{response.status_code} {response.headers.get('date', '')}\n\n"
            f"{response.text[:2000]}",
        )
    if not response.ok:
        try:
            data = response.json()
        except ValueError:
            data = {}
        if problems := data.get("problems"):
            # Publishing a draft which can't be adopted like this
            terminate("\n".join(f"- {problem}" for problem in problems))
        # Error pages of the server or a proxy aren't JSON, only their start
        detail = data.get("detail") or " ".join(response.text.split())[:200]
        terminate(f"{response.status_code}: {detail}")
    return response.json()


class _Loader(yaml.SafeLoader):
    """Keeps dates as strings, the server parses them"""


_Loader.yaml_implicit_resolvers = {
    key: [r for r in resolvers if r[0] != "tag:yaml.org,2002:timestamp"]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def load(file):
    """Load data from a YAML or JSON file"""
    try:
        return yaml.load(file, Loader=_Loader)
    except yaml.YAMLError as exc:
        terminate(f"Invalid YAML or JSON: {exc}")


def format_bool(value):
    return "true" if value else "false"


def echo_json(data):
    click.echo(json.dumps(data, indent=2, ensure_ascii=False))


def link(text, url):
    """Text which links to the URL in terminals supporting hyperlinks"""
    return Text(str(text), style=Style(link=url)) if url else str(text)


def make_table(*columns, **kwargs):
    """A table with headings, columns ending in ">" are right-aligned, those
    ending in "…" stay on one line and are shortened"""
    shortened = any(column.endswith("…") for column in columns)
    # The shortened columns get the width the others leave
    table = Table(box=box.SIMPLE_HEAD, expand=shortened, **kwargs)
    for column in columns:
        if column.endswith(">"):
            table.add_column(column[:-1], justify="right")
        elif column.endswith("…"):
            table.add_column(column[:-1], no_wrap=True, overflow="ellipsis", ratio=1)
        else:
            table.add_column(column, no_wrap=shortened)
    return table


def echo_fields(title, fields, *, url=None):
    """A bold title followed by the non-empty fields"""
    console.print(link(title, url), style="bold")
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim")
    grid.add_column()
    for label, value in fields:
        if value:
            grid.add_row(label, value if isinstance(value, Text) else str(value))
    console.print(grid)


def _flatten(row, prefix=""):
    """Nested objects become columns like ``project.code``, lists are joined"""
    result = {}
    for key, value in row.items():
        if isinstance(value, dict):
            result |= _flatten(value, f"{prefix}{key}.")
        elif isinstance(value, list):
            result[f"{prefix}{key}"] = ", ".join(
                json.dumps(item, ensure_ascii=False)
                if isinstance(item, (dict, list))
                else str(item)
                for item in value
            )
        else:
            result[f"{prefix}{key}"] = "" if value is None else value
    return result


def without(row, key):
    return {k: v for k, v in row.items() if k != key}


def echo_csv(rows):
    rows = [_flatten(row) for row in rows]
    writer = csv.DictWriter(
        sys.stdout, fieldnames=list(dict.fromkeys(key for row in rows for key in row))
    )
    writer.writeheader()
    writer.writerows(rows)


@click.group(cls=_Group)
@click.version_option(VERSION)
@click.option(
    "-i",
    "--installation",
    metavar="NAME",
    expose_value=False,
    callback=_select_installation,
    shell_complete=complete_installations,
    help="Use another installation for this command, any unique part of its URL.",
)
def cli():
    pass


def text_or_stdin(value):
    """Texts given as ``-`` are read from stdin"""
    return sys.stdin.read() if value == "-" else value
