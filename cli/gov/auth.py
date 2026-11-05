"""Logging in, installations, shell completion and who you are"""

import click
from click.shell_completion import (
    BashComplete,
    FishComplete,
    ZshComplete,
    add_completion_class,
    get_completion_class,
)

from gov import core
from gov.core import (
    browser_login,
    cli,
    complete_installations,
    console,
    echo_fields,
    echo_json,
    find_installation,
    installation_url,
    link,
    make_table,
    read_config,
    request,
    save_config,
    terminate,
    write_config,
)


@cli.command()
@click.argument("url", required=False)
@click.option(
    "--token",
    "paste_token",
    is_flag=True,
    help="Paste a token from the API tokens page instead of using the browser.",
)
@click.option(
    "--read",
    "access",
    flag_value="read",
    help="gov may only read, e.g. for tools which shouldn't change anything.",
)
@click.option(
    "--write",
    "access",
    flag_value="write",
    help="gov may read and write, e.g. create and publish proposals.",
)
def login(url, paste_token, access):
    """Authorize gov to access the governance in your name

    Opens the browser; the URL defaults to the current installation. Choose
    the access explicitly with --read or --write. Logging in to another
    installation adds it and makes it the current one (see `gov auth`). Use
    --token on computers without a browser, the token's access is chosen when
    creating it."""
    if not (url := url or read_config()["current"]):
        terminate("Which installation? Run `gov login URL --read` or `--write`.")
    url = installation_url(url)
    if paste_token:
        save_config(url, click.prompt("API token", hide_input=True).strip())
        click.echo(f"Saved {core.CONFIG}")
    elif not access:
        terminate("Choose the access: `gov login --read` or `gov login --write`.")
    else:
        browser_login(url, access)


class _CompleteOptions:
    """Offer the options when there's nothing else to complete, Click only
    does this when a dash has been typed"""

    def get_completions(self, args, incomplete):
        completions = super().get_completions(args, incomplete)
        # After an option its value may be expected, e.g. an ID
        if not (completions or incomplete or (args and args[-1].startswith("-"))):
            completions = super().get_completions(args, "-")
        return completions


for _shell, _class in [
    ("bash", BashComplete),
    ("zsh", ZshComplete),
    ("fish", FishComplete),
]:
    add_completion_class(type(_class.__name__, (_CompleteOptions, _class), {}), _shell)


@cli.command()
@click.argument("shell", type=click.Choice(["bash", "zsh", "fish"]))
def completion(shell):
    """Print the script which completes gov's commands in your shell

    bash: echo 'eval "$(gov completion bash)"' >> ~/.bashrc

    zsh: echo 'eval "$(gov completion zsh)"' >> ~/.zshrc

    fish: gov completion fish > ~/.config/fish/completions/gov.fish"""
    complete = get_completion_class(shell)(cli, {}, "gov", "_GOV_COMPLETE")
    click.echo(complete.source())


@cli.group(invoke_without_command=True)
@click.pass_context
def auth(ctx):
    """Switch between the installations you're logged in to

    `gov login URL` adds installations. Switching affects all terminals;
    setting GOVERNANCE_URL uses another installation in one terminal only,
    `gov -i NAME` for a single command.

    Without a command, lists the installations."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(list_installations)


@auth.command("list")
def list_installations():
    """List the installations, the current one is marked with *"""
    config = read_config()
    if not config["installations"]:
        terminate("Not configured yet. Run `gov login URL` first.")
    for url, installation in sorted(config["installations"].items()):
        access = installation.get("access")
        click.echo(
            f"{'*' if url == config['current'] else ' '} {url}"
            + (f" ({access})" if access else "")
        )


@auth.command("switch")
@click.argument("name", shell_complete=complete_installations)
def switch_installation(name):
    """Use another installation, NAME is any unique part of its URL"""
    url = find_installation(name)
    config = read_config()
    config["current"] = url
    write_config(config)
    click.echo(f"Using {url}")


@cli.command()
@click.option("--json", "as_json", is_flag=True)
def me(as_json):
    """Who you are and your roles (to choose the role of a proposal)"""
    user = request("GET", "me/")
    if as_json:
        echo_json(user)
        return
    echo_fields(
        user["name"],
        [
            ("Email", user["email"]),
            ("Page", user["url"]),
            ("Access", "read only" if user["access"] == "read" else "read and write"),
        ],
        url=user["url"],
    )
    # Grouped by circle, in the organization's order
    table = make_table("ID>", "Role", "Focus", title="Your roles")
    circle = None
    for role in user["roles"]:
        if role["circle_id"] != circle:
            circle = role["circle_id"]
            table.add_row("", role["circle"], "", style="bold")
        table.add_row(
            link(role["id"], role["url"]),
            link(f"  {role['name']}", role["url"]),
            role["focus"],
        )
    console.print(table)
