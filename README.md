# Governance

A Django app for running an organization with the
[Holacracy Constitution 5.0](docs/constitution/README.md): circles, roles
with their purpose, accountabilities and domains, policies, elections,
async proposals, governance and tactical meetings, and the complete
history of how the structure changed and why. It replaces GlassFrog at
[Feinheit](https://www.feinheit.ch/) and imports its data, including the
history.

The interface is German first (and English); the Holacracy terms stay
English like in the handbook.

- [`docs/`](docs/README.md): the user documentation in English and German
  (`name.de.md`), also available as help pages in the app
- [`SPEC.md`](SPEC.md): what the app does and why, the choices about the
  constitution, the backlog
- [`AGENTS.md`](AGENTS.md): running the tests, conventions, development
  and deployment
- [`cli/`](cli/README.md): `gov`, a command line interface for the API

## Development

Python 3.15 with [uv](https://docs.astral.sh/uv/), PostgreSQL, Node with
[mise](https://mise.jdx.dev/) for the frontend bundle:

    uv sync
    mise exec -- yarn install
    ./runtests.sh

See `AGENTS.md` for the development server, the translations and the
import from GlassFrog.

## License

BSD 3-Clause, see [`LICENSE`](LICENSE). The Holacracy Constitution's texts
are licensed under CC BY-SA 4.0 by HolacracyOne, `audit.sql` under the
PostgreSQL License, see [`NOTICE`](NOTICE).
