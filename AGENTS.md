# Governance

A Django app replacing GlassFrog: circles, roles, accountabilities, domains,
policies, elections, async proposals and governance meetings, following the
Holacracy Constitution 5.0. `SPEC.md` describes what the app does and why,
the GlassFrog data, the constitution choices and the backlog; read it
before working on anything, and update it when a decision changes.

The code and the conventions come from
[Workbench](https://github.com/matthiask/workbench) (checked out in
`~/projects/sites/workbench`, see its `AGENTS.md`). Copy what fits instead
of depending on it, and keep its conventions unless this file says
otherwise. This project is BSD-3 licensed (Feinheit AG), Workbench is GPLv3:
only copy code Feinheit holds the rights to (check `git log` of the file
there), not other contributors'. Parts with their own licenses are listed
in `NOTICE` (the constitution's texts, `audit.sql`).

# Running tests

Use `./runtests.sh` to run the full test suite. Accepts an optional module
argument:

```
./runtests.sh
./runtests.sh governance.roles.test_roles
```

The tests need the local PostgreSQL container: `podman start local_postgres_1`.

End-to-end tests (tagged `e2e`, e.g. `governance/meetings/test_e2e.py`) run
the real server and Chromium through Playwright: `uv run playwright install
chromium` once, without the browser they're skipped, `./runtests.sh
--exclude-tag e2e` leaves them out. They need the production bundle in
`static/`, which `./runtests.sh` builds first (`yarn rspack build --mode
production`). Add one when changing how the meeting page behaves in the
browser (htmx), the test client doesn't run JavaScript.

The meeting page uses htmx 4 (npm's `htmx.org@next`, in the bundle with
everything else, it does nothing on pages without `hx-` attributes;
`meeting.js` comes before it in `frontend/main.js`): inheritance is explicit
(`hx-target:inherited` etc.), the meeting's region `#meeting` is boosted,
links only when marked `data-in-meeting` (`meeting.js`), and the drafting
views go back to `?next=` (`drafting.done()`, `HX-Location` for htmx).

# Fixing bugs

1. Write a test which reproduces the bug.
2. Run it and make sure it fails, and fails for the right reason.
3. Simplify the test down to the essential behaviour.
4. Run it again and make sure it still fails.
5. Only then implement the fix and confirm the test passes.

# User documentation

`docs/*.md`, German and succinct, explains the tool (not Holacracy) and
what it doesn't do; `/help/` renders it (`governance/help.py`, add new
pages to `PAGES`). The files link each other relatively (`meetings.md`).
Update them in the same commit when a change affects what users see.

# Translations

German first. Update and compile the translation catalog with:

```
fl mm   # makemessages
fl cm   # compilemessages
```

`fl mm` only reads `.html`, `.txt` and `.py` files, so templates of other
formats end with `.txt` (e.g. the Markdown export `roles/governance.txt`).
Edit `conf/locale/de/LC_MESSAGES/django.po` manually. Remove the `#, fuzzy`
flag before any new entry or it won't be used. The Holacracy terms stay
English like in the handbook and in GlassFrog (Purpose, Accountabilities,
Domains, Policies, Tactical and Governance Meeting), as do the core roles'
names and constitutional texts; circles, roles, proposals and tensions are
Kreise, Rollen, Vorschläge and Spannungen. Tests run in English
(`LANGUAGE_CODE` when testing), `governance/test_translations.py` checks the
German texts.

# Development server

`fl dev` runs Django and the rspack dev server (with hot reloading of the
styles); open the dev server's port (8000), it proxies Django. Without it
the pages have no styles and scripts. A Django of your own runs on 8001
(`uv run ./manage.py runserver 8001`), with a dev server of your own:
`HOST=127.0.0.1 PORT=4100 mise exec -- yarn rspack serve --mode=development
--env backend=8001`. Sign in with `/accounts/login/?force_login=EMAIL`
(only with `DEBUG`), or pass a session cookie from
`Client().force_login(user)` to a browser for screenshots, see Workbench's
`AGENTS.md`.

All styles and scripts are in `frontend/`, bundled by rspack into one CSS
and one JS file (`frontend/main.js`, `{% rspack_assets "main" %}` in
`base.html`; `rspack.config.js`, `rspack.library.js` from fh-fablib, don't
change the latter here): Bootstrap's parts the templates use
(`styles/bootstrap.scss`, including only the utility groups, responsive
variants, grid breakpoints, form parts and color variants of buttons,
alerts etc. in use: add them there when a template needs another one), the styles
(`styles/main.css`), the theme toggle, the mentions, the meeting and htmx,
and the circle browser (a Preact island, `circles/`, which `main.js` imports
only on its page: Preact and d3 are a chunk of their own). No core-js:
SWC's usage detection adds polyfills by guessing (`Array#map` as an
iterator helper), the browsers of browserslist's defaults have what the
scripts use (`rspack.config.js` overrides the rule's `env`). Node and yarn come
from `mise.toml`: `mise exec -- yarn install`. `rspack_assets` reads `tmp/`
with `DEBUG`, else `static/`, which the deployment builds (`yarn rspack
build --mode production`, minified). Only the end-to-end tests need the
bundle.

# Deployment

As a container like Workbench (`Containerfile`, `.containerignore`, the
build-only settings in `conf/_env`), deployed with `~/projects/argocd`'s
`fl deploy`, which builds the frontend into `static/` first (so
`.containerignore` must not exclude `static`) and pushes the deployed
commit to `latest/<app>`. The configuration comes from environment
variables named like the settings: `DATABASE_URL`, `SECRET_KEY`,
`ALLOWED_HOSTS`, `SECURE_SSL_HOST` and `SECURE_SSL_REDIRECT=True`
(django-canonical-domain redirects everything else there), `LIVE=True`,
`EMAIL_URL`, `BASE_URL`, `GOOGLE_CLIENT_ID`,
`GOOGLE_CLIENT_SECRET`, `SENTRY_DSN` and `SENTRY_ENVIRONMENT`, and until
the switchover `GLASSFROG_TOKEN`. Only
existing, active users sign in; new people come from the import until the
switchover, afterwards admins add them in the Django admin. The
cron jobs are in argocd's `governance/values.yaml`: `import_glassfrog
--api` at 03:00 UTC (until the switchover), `fairy_tasks` at 03:30, and
hourly `end_inactive_meetings` (meetings end and send their outputs a few
hours after their last activity, not only at night).
Without SMTP set `EMAIL_URL=console:`, error mails failing hide the real
error. Pods read the secret when they start: restart them after changing
it.

## Reinitializing the database

The import of the whole history needs the GlassFrog export with its git
history, which the server doesn't have, so it runs in the web pod from a
copy. Everything that only exists in the app is lost: proposals, drafts,
meetings, checklists etc. made here, API tokens, `notify_all`. People
sign in again: the session cookies check the password field, which the
import fills with a new unusable password. Takes a few minutes, the
import itself one; not around 03:00, when the nightly import runs.

1. `git pull` in `~/projects/glassfrog`.
2. Deploy as usual (`fl deploy governance ~/projects/sites/governance` in
   `~/projects/argocd`). When the migrations were recreated, their names
   are all recorded in the old database, so the PreSync migration changes
   nothing.
3. Empty the database as its owner (the app's role, PostgreSQL 15 and
   later; else with the dbadmin DSN): `fl psql governance`, then
   `DROP SCHEMA public CASCADE; CREATE SCHEMA public;`. The pages fail
   until step 5.
4. Find the web pod (`kubectl -n prod get pods`, `governance-…` without
   `-import-`, `-fairy-`, `-end-` or `-migrate-`) and run
   `POD=governance-…`.
5. Migrate: `kubectl -n prod exec $POD -c governance -- .venv/bin/python
   manage.py migrate`.
6. Copy the export and import it:

   ```
   tar -C ~/projects -cz glassfrog | kubectl -n prod exec -i $POD -c governance -- tar -C /tmp -xz
   kubectl -n prod exec $POD -c governance -- .venv/bin/python manage.py import_glassfrog /tmp/glassfrog
   kubectl -n prod exec $POD -c governance -- rm -rf /tmp/glassfrog
   ```

7. Sign in and check the organization, the history and a proposal. The
   nightly jobs continue as before; `fairy_tasks` writes today's snapshot
   only when something changed.

The first import ran on 2026-11-04, the migrations were recreated on
2026-11-05 (`audit.operations.audit_tables()` adds the audit trigger in
the apps' initial migrations).

# GlassFrog data

- The GlassFrog export lives in `~/projects/glassfrog` (`feinheit/glassfrog`,
  private). A fetcher on a server commits it daily (`scripts/fetch_glassfrog.py`
  here); `git pull` to update, never commit or push to that repository
  yourself, the fetcher doesn't pull and its push would fail.
- `glassfrog.json` has a git history since 2018-11-16, the other files
  (proposals, meetings, roles with accountability texts, …) since
  2026-11-04. Section 1 of `SPEC.md` lists what they contain and their
  quirks.
  Add new findings there.
- Our governance data never goes into this repository: no exports,
  fixtures or test data from GlassFrog, no real names. Tests and examples
  use made-up circles, roles and people.
- Scripts reading the export run with `python3 -I` from a directory outside
  the export, and keep scratch files in a temporary directory which is
  deleted afterwards.
- The API token is in the server's environment (`GLASSFROG_TOKEN`), never
  in files of this repository.

# Conventions

- Circles are roles (`Role.is_circle`), not a separate model. A circle's
  purpose, accountabilities and domains are those of its role.
- Governance changes go through proposals, whose `instructions` use
  GlassFrog's JSON-patch-like format (`add`, `replace`, `remove`, `move`,
  `test`, with `original_value`). Only assignments and a role's policies
  for its domains (`roles/domain_policies.py`, recorded as adopted
  proposals) bypass the process; spelling goes through governance too.
  Archive instead of deleting.
- Core roles and their constitutional accountabilities come from code, not
  data (`governance/roles/constitution.py`).
- Metrics and checklist items belong to a role (a circle for its own),
  tactical meetings may be called for any roles.
- Drafts of proposals (also tensions) are private to their proposer
  (`Proposal.objects.visible_to(user)`).
- Texts mention roles as `@[Name](role:ID)` (`governance/roles/mentions.py`),
  rendered with the current name by the `markdown` filter; use the `plain`
  filter for snippets. Textareas of the forms get `data-mentions` (the
  form mixin), which `mentions.js` autocompletes; add it to textareas
  written by hand.
- History: `history.Snapshot` is the structure of a day (valid until the
  next one), `history.Change` the differences between consecutive
  snapshots (`update_changes()`), proposals say why. Daily jobs go into
  `./manage.py fairy_tasks` like in Workbench; it writes today's snapshot
  (`take_snapshot()`) when something changed. Circles in the
  organization's order: `Role.objects.depth_first()`.
- Badges are tinted in tones (`wb-tone-*` in `main.css`, light and dark):
  states and kinds through the `tone` filter (`badge {{ x.status|tone }}`),
  role kinds in the circle browser's colors (circle blue, core and
  elected purple). Red only for objections; removing is housekeeping, gray.
- Actions and projects stay in the task management tool; don't build
  them here. No
  integration with Workbench either (see the decisions in `SPEC.md`).
- Page layout, styles (light and dark mode), templates, the audit log and
  the API follow Workbench. The API (django-ninja, `governance/api.py`,
  one router per app) authenticates with personal tokens before the
  session (`accounts/api_auth.py`); `/api/` is exempt from the login
  middleware, so is `/accounts/` (protect views there with
  `login_required`). Charts and visualizations are server-side SVG
  or a small React island, the pages work without JavaScript.
- The `gov` command line interface lives in `cli/` (a separate package,
  installed with `uv tool install`, here with the dev dependencies),
  copied from Workbench's `wb`: a thin client of the API, keep the logic
  on the server. Commands follow `gov <noun> <verb>`; one module per noun
  (`cli/gov/proposals.py`), `cli/gov/core.py` has the configuration,
  requests and output helpers. `gov login` gets a token through
  `/cli-login/` in the browser, which posts it to a server the CLI runs on
  a local port. Bump the version in `cli/pyproject.toml` when changing the
  CLI, the server tells older ones to upgrade (`governance/cli_version.py`,
  raise `MINIMUM` when older ones don't work anymore).
  `governance/test_cli.py` runs the real commands against the API (requests
  go through Django's test client); add a test there for new commands.
- Use `speckenv` to load `.env` files in standalone Python scripts.
- Pre-commit hooks (via `prek`, not `pre-commit`) run on commit, ruff
  included, and auto-fix formatting. If a commit fails due to formatting,
  re-stage the auto-fixed files and commit again.

# Committing

- **Commit a lot and push a lot.** Commit every self-contained step as soon
  as it works (a model, a view, a fix, a spec update), and push right
  after committing. Don't collect changes for a batch commit at the end of
  a session; unpushed work is lost work when switching computers.
- One self-contained change per commit, with tests and docs (`SPEC.md`,
  this file) in the same commit.
- Stage files explicitly (`git add path …`), never `git add -A` or `.`:
  parallel sessions may share the checkout.
- No attribution trailers in commit messages (no `Co-Authored-By:`, no
  "Generated with ..." footers).
- Commit messages are written in English.
- Work on `main` directly, no feature branches. Fast-forward instead of
  creating merge commits whenever possible.
