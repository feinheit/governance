# Governance

A Django app which replaced GlassFrog: circles, roles, accountabilities,
domains, policies, elections, async proposals and governance meetings, following the
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
While a meeting runs, the secretary amends its proposals only there (the
proposal's page points to the meeting); don't add links leading those
running it out of the meeting.

Short forms open in a modal: `data-modal` on the link (`modal.js`, a
`<dialog>` outside of `#meeting`, loaded by htmx with `HX-Modal`). Views
rendering `generic/object_form.html` and redirecting need nothing else
(`governance/modals.py`: the template renders only the form, redirects
become `HX-Redirect`); `governance/test_modals.py`, the browser in
`test_e2e.py`'s `test_modals`.

# Fixing bugs

1. Write a test which reproduces the bug.
2. Run it and make sure it fails, and fails for the right reason.
3. Simplify the test down to the essential behaviour.
4. Run it again and make sure it still fails.
5. Only then implement the fix and confirm the test passes.

# Verification rounds

From time to time (or when asked what we're missing), look for behaviour
the tests don't cover, above all scenarios combining features over time:
async proposals and meetings, restructuring (moving, removing, circles
turning back into roles), assignments, elections, domain policies, mails,
the history, the API and `gov`.

1. A fresh agent reads `SPEC.md`, this file, the code and the tests,
   read-only and without our hypotheses. Tell it what's covered already
   (the scenario tests below, `git log --grep=Test:`) and to separate
   verified bugs (shown with a throwaway test it deletes afterwards) from
   untested risks.
2. Check its findings against the code before relying on them.
3. Ask the user where the behaviour is a decision rather than a bug.
4. Fix bugs as above (failing test first), one commit each, docs and
   spec included. Whole meetings go into
   `governance/meetings/test_scenarios.py`, API and CLI round trips into
   `governance/test_cli.py`.
5. Keep the open findings in the backlog of `SPEC.md` ("Verification")
   until they're done, so that the next session continues there.

# User documentation

`docs/`, succinct, explains the tool (not Holacracy) and what it doesn't
do: `name.md` in English, `name.de.md` in German, each quoting the labels
of the interface in its language. `/help/name/` renders them in the
page's language (`governance/help.py`, add new pages to `_NAMES`). The
files link each other relatively within their language (`meetings.md`,
`meetings.de.md`). Update both in the same commit when a change affects
what users see; `mails.md` lists every mail with its recipients.

# Translations

German first. Update and compile the translation catalog with:

```
fl mm   # makemessages
fl cm   # compilemessages
```

`fl mm` only reads `.html`, `.txt` and `.py` files, so templates of other
formats end with `.txt` (e.g. the Markdown export `roles/governance.txt`).
Edit `conf/locale/de/LC_MESSAGES/django.po` manually. Remove the `#, fuzzy`
flag before any new entry or it won't be used. Remove obsolete
entries (`#~`): `msgattrib --no-wrap --no-obsolete -o FILE FILE` after
`fl mm`. The Holacracy terms stay
English like in the handbook and in GlassFrog (Purpose, Accountabilities,
Domains, Policies, Tactical and Governance Meeting, Role Lead for who
fills a role, next to Circle Lead), as do the core roles'
names and constitutional texts; circles, roles, proposals, tensions and
metrics are Kreise, Rollen, Vorschläge, Spannungen and Metriken; a meeting's agenda and its items
are Agenda and Agendapunkte like in the German constitution
(`docs/constitution`), not Traktanden. Gender-neutral German, try hard: avoid pronouns for people and roles
("ist die Rolle nicht besetzt" instead of "fehlt er"), and articles on
the core roles' names, which make whoever fills them male: "wer Secretary
ist", "die Rolle Circle Rep", "seine Rollen Facilitator, Secretary und
Circle Rep", the names alone in lists ("sonst Facilitator"), not "der
Secretary" or "ein Circle Lead"; roles take "ihre" ("%(role)s für ihre
Domains"). Rephrase before reaching for forms: "wer die Rolle hat"
instead of "Inhaber:innen", "alle" instead of "jeder"; else neutral
forms (Mitarbeitende, Teilnehmende), the colon (Reviewer:in) only as a
last resort, never the asterisk: the colon survives bad Markdown parsers
like GlassFrog's. Pronouns for things (proposals, circles) stay
grammatical. Tests run in English
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
the keyboard shortcuts (`shortcuts.js`, `data-shortcut` on links and fields,
listed in `docs/orientation.md`), the icons (npm's `bootstrap-icons`, only
those in use in `styles/icons.css`, `{% icon "pencil" %}`, icon-only
buttons with a title and a visually hidden label; `test_icons.py`), the
drag handles of the agenda and of accountabilities (`sortable.js`,
SortableJS, a chunk of its own),
textareas growing with their text (`autogrow.js`), parts of forms
shown for some choices only (`shown_for.js`, `data-shown-for`), menus of what
isn't needed often (`details.wb-menu` with Bootstrap's `.dropdown-menu`,
`menus.js` closes them) and the circle browser (a Preact island, `circles/`, which `main.js` imports
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
`EMAIL_URL`, `MAIL_COPIES` (e.g. `["a@example.com"]`, who gets a copy of
each mail), `BASE_URL`, `GOOGLE_CLIENT_ID`,
`GOOGLE_CLIENT_SECRET`, `SENTRY_DSN` and `SENTRY_ENVIRONMENT`. Only
existing, active users sign in; admins add new people in the Django admin.
The cron jobs are in argocd's `governance/values.yaml`: `fairy_tasks` at
03:30 UTC (the history's changes, pruning API tokens, the reminders), and
`hourly_tasks` at a quarter past each hour (adopting async proposals at
their deadline, `Proposal.adopted_on` knows the minute; meetings end and
send their outputs a few hours after their last activity).
Without SMTP set `EMAIL_URL=console:`, error mails failing hide the real
error. Pods read the secret when they start: restart them after changing
it.

# GlassFrog data

The app replaced GlassFrog in November 2026. Its data was imported, with
the history since 2018 (the importer, `governance/glassfrog/`, is in the
git history, removed after the switchover): the models keep their
`glassfrog_id`s, proposals adopted in GlassFrog refer to GlassFrog's IDs
(`Proposal.adopted_in_glassfrog`), the audit log's rows before the app
belong to "GlassFrog" (`history/backfill.py` writes rows like them, the
tests use it). Section 1 of `SPEC.md` describes the export
(`~/projects/glassfrog`, `feinheit/glassfrog`, private, no longer
updated). Our governance data never goes into this repository: no
exports, fixtures or test data from it, no real names. Tests and
examples use made-up circles, roles and people. `scripts/fetch_backup.py`
commits the app's JSON backup daily to a git repository instead.

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
- History: the audit log has every change of roles, accountabilities,
  domains and policies, the GlassFrog import backfilled the time before
  the app (`history/backfill.py`); `structure_on(day)` is the structure of a
  past day, `history.Change` the differences from day to day computed from
  it (`update_changes()`), proposals say why. Tests reading the audit log
  delete its rows first: other tests (end-to-end) commit theirs and the
  audit table isn't flushed. Daily jobs go into `./manage.py fairy_tasks`
  like in Workbench (hourly ones into `hourly_tasks`); it updates the history's changes of yesterday and
  today. Circles in the organization's order: `Role.objects.depth_first()`.
- Badges are tinted in tones (`wb-tone-*` in `main.css`, light and dark):
  states and kinds through the `tone` filter (`badge {{ x.status|tone }}`),
  role kinds in the circle browser's colors (circle blue, core and elected purple), ad hoc tactical meetings hollow and dashed (not a circle's, `Meeting.kind_key`). Red only for objections; removing is housekeeping, gray.
  Changed texts are diffs (`governance/diff.py`, the `diff` filter):
  removed words red, added green, like diffs elsewhere.
  Buttons: `btn-destructive` (red ink) for deleting, removing somebody,
  withdrawing, `btn-danger` confirming it; buttons needing a permission
  check use `{% button_class right %}`, amber (`btn-elevated`) when done
  as admin or as Secretary standing in for the Circle Leads; forms
  passing `right` to their template explain it (`generic/_right.html`).
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
  `cli/skills/` has Claude Code skills using `gov` (e.g.
  `governance-proposal`, a draft from a tension, `governance-review`);
  `governance/test_skills.py` checks that their examples of instructions
  are what the server takes and that the `gov` commands they use exist.
- Model methods changing data without required arguments get
  `alters_data = True`: templates must not call them (overridden
  `save()` and `delete()` keep Django's, its `AltersData` copies it).
- Use `speckenv` to load `.env` files in standalone Python scripts.
- Pre-commit hooks (via `prek`, not `pre-commit`) run on commit, ruff
  included, and auto-fix formatting. If a commit fails due to formatting,
  re-stage the auto-fixed files and commit again.

# Committing

- **Commit a lot, push in batches.** Commit every self-contained step as
  soon as it works (a model, a view, a fix, a spec update). Push after a
  batch of them (each push runs the CI on GitHub), and always before
  ending a session: unpushed work is lost work when switching computers.
- One self-contained change per commit, with tests and docs (`SPEC.md`,
  this file) in the same commit.
- Cleanups along the way (obsolete translations, dead code, stale
  comments) are always fine, in commits of their own.
- Stage files explicitly (`git add path …`), never `git add -A` or `.`:
  parallel sessions may share the checkout.
- No attribution trailers in commit messages (no `Co-Authored-By:`, no
  "Generated with ..." footers).
- Commit messages are written in English.
- Work on `main` directly, no feature branches. Fast-forward instead of
  creating merge commits whenever possible.
