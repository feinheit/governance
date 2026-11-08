# Governance CLI

`gov` talks to the Governance JSON API: circles, roles, the search and
proposals. Commands follow the pattern `gov <noun> <verb>`, e.g.
`gov proposals show 12`; `gov --help` and `gov <noun> --help` list them.
Every command takes `--json` for scripts. IDs and names link to their
pages in terminals which support links.

Install it with [uv](https://docs.astral.sh/uv/):

    uv tool install "git+https://github.com/feinheit/governance#subdirectory=cli"

Upgrade it when `gov` tells you to, it prints the command.

Log in, which opens the browser to authorize `gov`. Choose the access
explicitly: `--read` only allows looking things up, `--write` also allows
creating, changing and publishing proposals. Read access is the safer choice
for tools and agents which only answer questions:

    gov login https://governance.feinheit.ch --read

Check it with `gov me`, which also lists your roles with their IDs. Access
expires 30 days after its last use; `gov` then opens the browser again by
itself. On
computers without a browser, create a token on the "API tokens" page and
use `gov login URL --token`.

Several installations work like in Workbench's `wb`: `gov auth list`,
`gov auth switch NAME`, `GOVERNANCE_URL` for one terminal and
`gov -i NAME` for one command.

Enable completing commands, options and IDs with Tab in your shell:

    echo 'eval "$(gov completion bash)"' >> ~/.bashrc     # bash
    echo 'eval "$(gov completion zsh)"' >> ~/.zshrc       # zsh
    gov completion fish > ~/.config/fish/completions/gov.fish   # fish

IDs of circles, roles, policies and proposals are completed with their
names (zsh and fish show them); typing a part of a name and Tab replaces it
with the ID. The names are cached in `~/.cache/gov`, the structure for a
day, your roles for an hour, proposals for five minutes.

## Reading

    gov circles                 # the circles as a tree
    gov circles show 12         # a circle with its roles and policies
    gov roles show 34           # a role with its texts and holders
    gov policies --circle 12    # a circle's policies, also its roles'
    gov policies show 78        # a policy with its text
    gov domains --circle 12     # domains with their policies
    gov search soup kitchen     # all terms, ignoring case and accents
    gov export -o governance.md # everything as one Markdown document
    gov export --json           # the JSON backup: everything, one key per file
    gov proposals --circle 12 --status published
    gov proposals show 56       # tension, changes, problems

## Preparing proposals

A draft needs the circle, one of your roles in it (see `gov me`) and the
tension; without instructions it stays a tension only you see. The
instructions use GlassFrog's format, in YAML or JSON, e.g. a new role:

    - op: add
      path: /roles/n1
    - op: add
      path: /roles/n1/name
      value: Baker
    - op: add
      path: /roles/n1/aim
      value: Bread for everyone

    gov proposals create --circle 12 --role 34 --tension - --instructions baker.yaml
    gov proposals update 56 --instructions baker.yaml
    gov proposals publish 56

The server checks the instructions and lists the problems which would
prevent adopting the draft; publishing refuses drafts with problems.
## Responding

    gov proposals open          # published in your circles, your response
    gov proposals consent 56    # no objection
    gov proposals request-meeting 56 --concern "Who washes the pots?"
    gov proposals comment 56 "Does this include the pots?"

Crashes write a bug report to `~/.cache/gov` instead of a traceback, set
`GOV_DEBUG=1` to see the exception.
