# Spec: Governance (replacing GlassFrog)

A Django app replacing GlassFrog: circles, roles, accountabilities,
domains, policies, elections, async proposals, governance and tactical
meetings, following the Holacracy Constitution 5.0
(`docs/constitution/`, the English original and the official German
translation, CC BY-SA). It keeps the
history since the first day of GlassFrog (2018), including why things
changed.

This file describes what the app does and why. The git history has the
earlier versions of the spec, also the phases of the build.

Out of scope on purpose:

- **Actions and projects**: a task management tool handles operational
  work. Roles and circles link to it (`Link`), tactical meetings link the
  tasks created.
- **Multiple constitutions**: only Holacracy 5.0. Core roles and their
  constitutional accountabilities come from code
  (`roles/constitution.py`), not data.
- **GlassFrog's workflow features** beyond the constitution (custom fields,
  tags, HubSpot, persisted filters).
- **Workbench integration**: Workbench had roles on services and hours by
  circle until 2022, which didn't prove useful. Policies referring to
  Workbench stay rules people follow.

## Stack

A separate project built from Workbench's code and conventions by copying,
not depending on it: Django, PostgreSQL, a reduced `User` (email, name,
short name, active, `notify_all`), Google sign-in (django-authlib) for
existing, active users, the audit log trigger, Workbench's page layout
(light and dark mode), django-ninja, the daily `fairy_tasks`, German
first. htmx 4 on the meeting page and for the modals, a Preact island for
the circle browser,
all styles and scripts in one bundle (rspack, only the parts of Bootstrap
in use).
Hosted at `governance.feinheit.ch` (see `AGENTS.md`).

Our governance data never goes into this repository: tests and examples
use made-up circles, roles and people.

## 1. GlassFrog data

`feinheit/glassfrog` (`~/projects/glassfrog`) is fetched daily by
`scripts/fetch_glassfrog.py` (token in `GLASSFROG_TOKEN`; writes only when
all requests succeeded, commits only changes).

**`glassfrog.json`** (`GET /api/v3/circles?include=members`) has a git
history since 2018-11-16: circles with their roles, policies, domains and
people. A snapshot is valid until the next commit. Quirks:

- **Stale circles**: GlassFrog keeps the circle record when a circle turns
  back into a role. A circle is live if it is the anchor or its
  `supported_role`'s `supporting_circle` points back to it.
- **Circles are roles**: a circle's purpose, accountabilities and domains
  are those of its supported role. Circles and roles have separate ID
  ranges; proposals use both (`/circles/N/roles/M`).
- Every `linked` list contains one `{}`; `tag_names` are always empty,
  `settings` is UI state.
- 12 empty commits (failed fetches); commit dates of the last 180 commits
  are local time labelled `+0000`, use the date of the commit message.
- Until 2022-12-13 Holacracy 4.1 (Lead Link, Rep Link), then 5.0 with new
  accountability IDs for the core roles.
- Until 2019-05-18 roles came in `linked.supported_roles` and policies
  linked their owner with `circle_id`/`role_id`.
- Only the circles' policies, no accountability texts (IDs only), some
  sub-circles' holders missing in the super-circle.
- Roles without people are held by the Circle Leads.
- The API shows people who left as "Removed" with a redacted email; the
  snapshots still have their names.

**The other files** (since 2026-11-04): `roles` (accountability texts),
`assignments` (focus, election term), `policies` (also those of roles for
their domains), `proposals` (1281, with tensions and instructions),
`tensions`, `governance_meetings`, `tactical_meetings` (agenda labels only,
no outcomes), `metrics`, `checklist_items`, `projects`.

**Proposal instructions** are JSON-patch-like with old values:

```json
{"op": "replace", "path": "/roles/123/accountabilities/456/description",
 "original_value": "Planning workshops", "value": "Planning and running workshops"}
```

Ops `add`, `replace`, `remove`, `move` and `test` (the target must still
exist). Paths cover roles (`name`, `aim` = purpose, `supporting_circle` =
convert to circle), accountabilities, domains, policies (`title`, `body`,
`links/domain`), moving roles and policies between circles, and elections
(`/roles/N/assignment/links/person`, `/roles/N/assignment/until`).

**Proposals are not the complete history.** Replaying them reproduces the
accountabilities of only 86 of 160 roles: the initial setup, direct edits
and spelling corrections bypassed them. Structure, names, purposes,
policies, domains and assignments are complete in the snapshots; older
accountability texts are known where proposals or `roles.json` have them.

## 2. Data model

- **`Role`**: one table for roles and circles (a circle is a role broken
  down into roles; converting is a flag, not a copy). `circle` (null only
  for the anchor), `name`, `purpose`, `position`, `is_circle`; circles
  have `short_name` and `strategy` (set by the Circle Leads, not
  governance). `core_role` (lead, facilitator, secretary, rep): created
  and removed with their circle, governance only adds accountabilities
  and domains to them (not to the Circle Lead, see the constitution
  choices). `archived_on` instead of deleting, `other_names` (earlier
  names, texts may mention them), `is_elected_by_policy`,
  `async_acceptance_days` (inherited by sub-circles; the anchor's policy
  says 4 days, one circle uses 1; GlassFrog has no setting for it, the
  import sets the default, 4, on the anchor circle unless set here), `glassfrog_id`/`glassfrog_circle_id`.
  The policies stay the explanation of these settings, the Secretary sets
  them on the "Settings" pages.
- **`Accountability`**, **`Domain`**: `role`, `text`, `position`.
- **`Policy`**: `role` (the circle, or a role for its domains), `title`,
  `body`, optional `domain`, `archived_on`.
- **`Assignment`**: `role`, `user`, `focus`, `elected_until`, `starts_on`,
  `ends_on`; ending keeps the row. A person holds a role once (a
  constraint), the focus lists everything; the import merges GlassFrog's
  assignments per focus (`importer.merged()`). Circle membership isn't stored: the
  holders of a circle's roles plus the Circle Leads and Circle Reps of its
  sub-circles (`permissions.members()`).
- **`Metric`**, **`ChecklistItem`**: `role` (a circle for its own items),
  `description`, `frequency` (weekly, monthly, quarterly, yearly or none;
  only groups them), `link`. Operational: the Circle Leads edit metrics,
  anybody edits checklist items (Holacracy defines no process), the audit
  log keeps their history. A circle's page lists its roles' items too.
  GlassFrog's "global" items, shown everywhere, aren't supported; items
  without circle and role belong to the anchor.
- **`Link`**: `role`, `title`, `url`, `description`; anybody edits them.
- **Users**: everybody named in GlassFrog's data, matched by email,
  people who left as inactive users. Afterwards admins add people, and
  deactivate those who leave in the Django admin, which ends their
  assignments (`roles.assignments.end_assignments_of()`, a Circle Lead's
  role in the super-circle too); their proposals stay.

**Mentions**: texts store `@[Name](role:ID)` and render the current name
as a link; textareas autocomplete "@" (`mentions.js`, `GET /api/roles/`).

**Text** is light Markdown in plain textareas, no rich text editor.

## 3. Proposals

**`Proposal`**: `circle`, `proposer`, `role` (the proposer's role with
the tension; GlassFrog's have none), `tension`, `instructions`
(GlassFrog's format), `names` (for rendering), `kind` (governance, policy
of a domain, legacy spelling correction), `status`, `published_at`,
`deadline`, `decided_at`, `meeting`, `glassfrog_id`.

GlassFrog's format makes the import 1:1, every proposal a readable diff,
and `test`/`original_value` detect conflicts instead of silently
overwriting. The interface never shows instructions: forms per operation
build them (`proposals/drafting.py`), pages render a diff. New objects use
keys like `n1` until adoption. `adopt()` (`proposals/instructions.py`)
applies all or nothing, validated against the constitution; the draft
page lists the `problems()` and `consequences()` adopting now would have;
published proposals show everybody their `consequences()` (decided
2026-11-07).
The meeting shows the `problems()` of the item being processed to
everybody, e.g. a role the proposal changes which a proposal adopted
earlier in the meeting changed too. Adopting stays blocked; the secretary
saves the role's (or policy's) form in the proposal once, which starts
from the proposal's values and rebuilds the instructions against the
current ones. Fields changed in the meantime which the proposal changes
differently are merged (`drafting.MergeMixin`): text areas start with
both versions between Git's conflict markers, single-line fields (name,
title) show the current value and need a confirmation. The proposal's
changes of accountabilities and domains removed in the meantime are
offered as new ones between markers (kept or dropped, not lost
unnoticed). Texts with
conflict markers are rejected, by the forms and when applying
instructions (also from the API) (an accountability removed in the meantime drops the
proposal's change of it).

States: `draft` → `published` (async) → `adopted`, or → `in_meeting` →
`adopted`/`withdrawn`. `in_meeting` ("waiting for a meeting") waits for
the next governance meeting: someone asked for one in their response, the
proposal is on an agenda or came up in a meeting (GlassFrog's `escalated`),
also when no meeting is running. Escalated GlassFrog proposals older than
two months (published, else created) and not on an agenda here are
imported as drafts: their proposers bring them again or delete them, admins
can't withdraw other people's proposals. GlassFrog stays the source of
truth for imported proposals until the switchover: the import overwrites
their status. Meetings here may adopt them to try the process (the next
import sets proposal and structure back), the async process doesn't. Drafts are private to the proposer until published
or brought into a meeting; a draft without instructions is a tension (the
tension inbox; GlassFrog's open tensions are imported as such). New
proposals ask for the tension, an example and how the proposal helps
(5.3.1).

**Who proposes**: a proposal addresses a tension of one of the proposer's
roles in the circle (5.3.1), chosen from `proposer_roles()`: the roles
held in the circle (also a sub-circle's role, held by its Circle Leads and
Rep), for the Circle Leads also the unfilled ones (1.4.2), not for the
Secretary standing in for them: they propose from the Secretary role and
say in the tension which role they speak for (decided 2026-11-07). Agenda items
turned into proposals get the owner's first role, the secretary changes
it if needed.

**What drafts change**: add, change, remove and move roles and policies of
the circle, convert roles and circles. Moves go into a sub-circle or any
sub-circle thereof and out of them into the circle, in one step (5.2;
moving roles into a role makes it a circle only for the circle's own
roles), not into a role's own inside; policies regulating a domain stay
with it (decided 2026-11-07). Removing a circle moves the
selected roles and policies to the super-circle and archives the rest
(like GlassFrog). Circles and roles removed (also inside a removed
circle) and circles turned back into roles close: their open proposals
(drafts too, and those for inside a role) are withdrawn, their running
meetings end (`instructions.close_circles()`), their proposers get a
mail; a proposal of an archived
circle or role isn't adopted. The anchor circle changes its own purpose,
accountabilities and domains through its own governance (1.3.3).

**Roles and circles convert automatically** (like GlassFrog 5):

- Adding roles inside a role is the role's own governance (1.3.1): its
  holders propose in the role, adopting makes it a circle with them as
  Circle Leads. With a single holder publishing adopts right away. Only
  the holders get the mails, not the circle containing the role: its
  structure inside is the role's own business (decided 2026-11-07). Moving
  roles into a role is the circle's governance and converts it too.
- A circle losing its last own roles turns back into a role (held by
  its Circle Leads, no longer by its Circle Rep) when
  adopting, or when its own meeting running meanwhile ends
  (`revert_after_meeting()`): the meeting goes on to its closing round,
  the proposal which left the circle without roles (also one of the
  super-circle, `Proposal.reverting_circles`) records the step; its core roles are archived and their assignments end, its
  policies without a domain are archived (a role only has policies for
  its domains, 1.3.2; the same proposal may move them up), those for its
  domains stay the role's, its holders change them again. Drafts say so beforehand, the
  adopted proposal records the steps. A role made a circle on purpose
  (without roles yet) stays one, also when its first meetings end
  without adding any: only a proposal emptying it turns it back.

**Async proposals**: circle members get a mail with the tension and the
diff. Publishing checks again that the proposer may propose from the
proposal's role (5.3.1), e.g. their assignment ended since drafting;
drafts without a role (a guest's item drafted again, drafts imported
from GlassFrog) get one first (decided 2026-11-07). Until the deadline (`async_acceptance_days`) members ask questions
(comments), consent ("no objection") or request a meeting, optionally with
the concern, which moves it to the next governance meeting. No async
objections, like GlassFrog: objections are tested in meetings, so async is
for uncontroversial changes. The proposer only answers questions. Adopted
when everybody else consented, or by the daily task at the deadline;
pages and mails show the day, not a time (`adopted_on`). Due proposals are
adopted in order of publication, conflicting ones go to the meeting.
Adoptions run one after the other (`instructions.lock_structure()`, an
advisory lock until the transaction ends), so that two at once check
against each other's changes.
Only circle members respond (also no admins outside the circle).
Responses are anonymous: consents and requests are only counted ("3 of 7
without objection"; current members only, not people who left since,
decided 2026-11-07); questions and concerns show their author because they
are answered and discussed with them. A published proposal can't be
edited: the proposer takes it back to its draft (responses since
republishing count) or withdraws it, not while its meeting runs (the
secretary discards it there, decided 2026-11-07). Somebody leaving the circle doesn't adopt a proposal early, even when
everybody remaining has consented: it waits for its deadline like
announced (decided 2026-11-06). Role and policy pages show pending
proposals (published or in a meeting): `Proposal.save()` keeps their
`roles` and `policies` those the instructions change now, also when
brought into or amended in a meeting; `adopt()` adds those it creates or
defers. The weekday restriction of one circle's policy stays a soft
rule.

**Outside the process**, recorded for the history:

- **Policies of a domain's role** (1.3.2, `roles/domain_policies.py`):
  the role's holders (the Circle Leads while unfilled) add, change and
  remove its policies on the role page, each with one of its domains.
  Every change is an adopted proposal of its own kind, mailed to the
  members of the role's circle and all its sub-circles, `notify_all`
  users and the person making the change. They move with their role,
  and are archived with it, with its circle or with their domain (the
  proposal removing the domain lists them). Only the role changes them:
  the circle's proposals don't, they may remove the domain. A role
  becoming a circle keeps them as the circle's own policies, which its
  governance changes from then on (a decision); turning back into a role
  they're the role's again.
- **Assignments** are operational: the Circle Leads assign and remove
  people and their focus (the super-circle's Circle Leads for a
  sub-circle's Circle Leads, admins for the anchor's). Elected roles aren't
  assigned this way. Holders resign through their Circle Leads, who end
  assignments of elected roles too ("Holders" on the role's page;
  `can_end_assignment()`, a Rep's hold of the circle's role ends with it).
- **Circle Leads**: a circle may have several, each with all the rights
  (texts speak of Circle Leads). While nobody holds a circle's Circle
  Lead role (its role in the super-circle), the super-circle's Circle
  Leads lead it, recursively (1.4.2, `permissions.circle_leads()`):
  they assign, propose from its unfilled roles and are its members. The
  same for a role nobody holds: its circle's Circle Leads are its
  holders (`role_leads()`), also for its inner circle. The anchor circle
  has Circle Leads only when assigned. Archived circles and roles have
  nobody: archiving ends their assignments, and nobody from above fills
  them in. Facilitator and Secretary follow
  the constitution's stand-ins (5.3.6); the app gives them no rights in
  meetings the other members don't have, except the secretary amending. An
  assignment removed on the day it started was a mistake and is deleted.
  Adopted proposals record whose assignments they ended
  (`Proposal.ended_holders`), so that the meeting's outputs reach them
  too. A circle's role follows its Circle Leads and Reps. Nobody leading a
  circle, also from above, is its Circle Rep (5.1.1): not elected, and
  when assigning or removing would make a Circle Rep lead their circle,
  the page warns and then ends the Circle Rep's assignment
  (`assignments.change_assignments()`), the circle elects a new one;
  proposals moving a circle under one its Circle Rep leads show it in
  their consequences and end it when adopted (`Applier.finish()`),
  deactivating ends it without asking.

Spelling corrections go through governance on purpose, like striking
invalid governance (4.2.2): the Secretary starts a governance meeting,
makes the change and adopts it. An earlier Secretary edit form was
removed; its corrections stay in the history.

## 4. Meetings

**`Meeting`**: circle, kind, started and ended, secretary,
`called_by`, `invited_roles` (tactical), attendees, minutes (the notes,
GlassFrog's scratch pad), current item
and step. Starting is calling: there is no prepared state, scheduling and
announcing happen in the calendar. Any circle member (and admins) starts
one (`can_start_meeting()`, not in archived circles; the list of
meetings and the circle's page lead to the running one instead), the holders of a role a governance meeting
inside it (1.3.1: its inner circle, adding roles makes it a circle; no
tactical meetings in a role). Starting asks first (`asks_before_starting()`,
a modal): in a role always, cancelling being the default (rarely what
people want, the role itself changes in its circle); in a circle those
who aren't its Secretary or standing in for them, starting being the
default. The meeting's secretary handles its buttons (`can_run()`):
steps, processing items, adopting, elections, attendees,
the notes, ending it; they also amend proposals. The others follow on
their own screens: the current step and agenda item are highlighted, the
item's proposal links to its page and summarizes what it proposes now,
updated while the secretary amends it (roles and policies added,
changed, removed, roles moved, `describe.summarize()`); in tactical meetings they look at
another review on their own screen (`?step=`, `REVIEW_STEPS`). The app doesn't record who
facilitates. The secretary is whoever starts it (also an ad-hoc
tactical meeting): those who aren't acting as the circle's Secretary
(`acting_secretaries()`: the Secretary, else the stand-ins of 5.3.6, the
Facilitator, then the Circle Leads; also for "Take over" and the
requests for a meeting) confirm starting it, they don't take over
afterwards. The members (and admins,
marked) take over (`can_take_over()`, "Take over", e.g. for a late
Secretary), the page asks those who aren't acting as the circle's
Secretary to confirm. Attendees are the members when it starts; the
secretary invites others (also guests of Circle Reps) and removes them.
One meeting at a time per circle (a constraint): starting another one
joins the running one, the circle page offers it instead. Ad-hoc tactical
meetings have no circle and may always run.
Nobody has to remember to end a meeting: changes to it, its agenda,
attendees, elections and the proposals processed in it set
`active_at` (`meetings/activity.py`, signals), and meetings inactive for
three hours end with their last activity (with the outputs mail as
usual): hourly (`end_inactive_meetings`), in `fairy_tasks` and when
somebody starts a meeting in the circle.
A line above every page shows the running meetings one attends (not in
the meeting itself, not the inactive ones; `{% running_meetings %}`).

All state lives on the server, people follow on a shared screen and add
agenda items from their own devices. **The meeting page** (htmx 4): actions
replace only `#meeting`, links navigate normally unless marked
`data-in-meeting`; every five seconds the region is morphed with the
server's, except while somebody types or has the panel or a section open
(paused longer than one check, a notice says so, `#meeting-paused`, but
not to the secretary amending the proposal in the panel).
Modals don't stop it: they're outside of `#meeting`.
While it runs the heading is in the left column, so that the right one
starts right below the navigation (an ended meeting has the usual
header with the date, who called it and the secretary, no scrolling
column). Left: the secretary ("Take over"), the agenda (compact rows
"description – short name"; the attendees in a modal and "End the
meeting" in its heading) (adding items as its last line, completed items
struck through, "End the meeting" at its bottom), for ad-hoc tactical
meetings the invited roles, elections, proposals. On wide screens both columns fit the window down to its lower edge and
scroll on their own, the page doesn't (`.wb-fit`, `fitFlow()`). On
phones and tablets one column, the page scrolls: the heading and the
secretary first, then the rounds and the flow, the agenda and the rest
below (the left column is `display: contents` there, `.wb-meeting-side`).
Right: the rounds, then one column (`.wb-flow`; in the closing round
only the notes and a large "End the meeting"): in tactical meetings the results of the
completed items while processing the tensions (a card each,
`_results.html`), the item being
processed, and the notes at the bottom (what doesn't belong to an agenda
item, e.g. a special meeting's intent; the secretary's textarea saves
itself, `data-autosave`). It scrolls to the item when another one is
processed and when its agenda row is clicked (`meeting.js`), sticky
beside the agenda's column; a completed item's row leads to its result,
"Reopen" makes it the current item again (`item_reopen`). Ending it is
celebrated once (`?celebrate=1`, an emoji, confetti and a thank you from
Workbench's logbook, without the confetti for reduced motion). An ended
meeting shows its outputs like its mail (`meetings/outputs.py`) and
doesn't change anymore (`runnable_meeting()`).
`meetings/test_e2e.py` covers it in a browser.

**Governance meetings**: check-in, agenda, closing (5.4.3). Members and
attendees add items while it runs (5.4.4): a tension in a few words, or a
proposal: their own, waiting for a meeting, published async (which ends
the acceptance period: re-proposed at the meeting, 5.3) or drafts (not
empty ones). Others' proposals wait for their proposers, whom members ask
by requesting a meeting; only those running the meeting also bring
others' waiting and async proposals, in an optgroup of their own (the
proposer asked them and isn't there). The select starts empty. Removing
the item puts them back (`AgendaItem.proposal_status`, waiting ones and
tensions turned into proposals wait for the next meeting, none of them
points to this one anymore); an async proposal
the meeting processed (`AgendaItem.step`, maybe amended) becomes its
proposer's draft instead, publishing it again starts a new round with a
new deadline: the old consents were to another version (5.3). The secretary processes items (clicking
the row, which also goes to the step processing them: only there an item
is active, `Meeting.active_item_id`), orders them with drag handles (`agenda_order`, without
JavaScript arrows)
in any order; buttons for the six steps of integrative decision-making
guide without enforcing them. Only the secretary amends, with the drafting
controls in a panel, and captures a proposal from a tension. While the
meeting runs, its proposals are amended there only: the proposal's page
points to the meeting instead of offering the drafting controls, the
agenda links proposals to their pages only for those not running it (the
sidebar's list of the meeting's proposals shows once it isn't running). "Discard"
withdraws the item's proposal (5.3.1, 5.3.4), the outputs list it, its
proposer gets a new draft of it with "Draft again"; "Done" leaves it
waiting for the next meeting. Objections aren't recorded (decided
2026-11-06): the facilitator asks for and tests them in the objection
round, the secretary integrates valid ones by amending the proposal, the
meeting's notes keep what matters. Adopting needs a proposer still
filling the proposal's role (5.3.1, like publishing): a guest's tension
needs a member owning it, the secretary chooses the role of proposals
without one. Concerns of members who
requested the meeting are shown as context. Adopting changes the
governance at once; the mail waits for the end.

**Elections** (`meetings/elections.py`): the facilitator runs the
integrative election process (5.3.5) without the app, which records the
result (person, term end) for Facilitator, Secretary, Circle Rep and
roles elected by policy. Only circle members are candidates, Circle
Leads aren't the Rep: an unfilled Circle Rep is nobody's (not held by the
Circle Leads like other unfilled roles, not a role to propose from). Re-electing changes the term, electing somebody else
ends the previous assignment (removed if it only started today), a Rep
also holds the circle's role in the super-circle. Elected roles have one
holder: recording the same role again in the meeting (a correction, a
second vote) replaces the earlier result, undone first (`Election`
keeps what it changed: the previous holder keeps their assignment). Due elections (within 30 days, nobody elected, or held without a
term, e.g. a role made elected by policy while held; terms end in the
future) show on
the circle page and the Facilitator's and Secretary's person pages;
Facilitators (5.3.5; else Secretaries, else Circle Leads) get a mail
on Mondays.

**Tactical meetings** (article 3): any circle member
starts a regular one (all roles of the circle invited, attendees its
members); anybody calls an ad-hoc one from a role page, inviting roles of
any circle. Steps: check-in, checklist review, metrics review (the
invited roles' entries, for regular ones also the circle's own, not a
sub-circle's own), progress updates (the links of the circle and the
invited roles, the outcomes and links of the circle's last three
tactical meetings having some, "Show earlier meetings" ten, then ten
more, `?earlier=`, which the page's updates keep; `progress_context()`),
agenda, processing tensions,
closing. An item may record an outcome and a link, both optional, saved
while the secretary types (`data-autosave`, `X-Autosave`, the others
see it with their next update; "Save and done" completes the item): many
items end with information, next actions and projects live in the task
management tool (several of them are one link to a to-do list), and a
governance tension is captured by its owner as a tension of their own
(the app doesn't add tensions for others). GlassFrog's actions and
projects aren't imported.
Open meetings are listed on the attendees' person pages.

## 5. Notifications

Plain text mails per active recipient in their language (none for
people who left, also as proposers), after the transaction commits (`notifications/mails.py`), to the circle's members: published
async proposals, those taken back, those their proposer withdraws
(published or waiting for a meeting, `process.retract()`), those which
can't be adopted async and wait for a meeting (a conflict at the
deadline or the last consent, `mails.proposal_to_meeting()` with the
problems; not imported ones, which the nightly import sets back), adopted ones with the diff (also to
the proposer, and to the members before adopting, e.g. the holders of
roles the proposal removes or moves away, and the Secretaries, who
invite them to meetings, and Circle Leads of the sub-circles it moves
roles or policies into or out of, `mails.moved_between()`), domain policy changes (section 3), and when a meeting ends
its outputs (adopted proposals, elections, notes, tactical outcomes;
also to the attendees and, like adopting async, the holders of roles
the adopted proposals changed, removed or moved away, also deeper inside:
roles of a removed circle, core roles of a circle turned back, and the
sub-circles' Secretaries and Circle Leads like adopting async). A
circle emptied by its super-circle while its own meeting ran turns back
when that meeting ends: those losing its core roles get the mail about
their roles then. Like GlassFrog, assignments, removals, elections
and deactivations (`roles.assignments.announce()`; elections when the
meeting ends, the results after corrections only, not those of core
roles archived by the circle turning back then:
`elections.announce_elections()`, decided 2026-11-07) tell people the roles
they get and lose (not the circle's role in the super-circle, which
follows the core roles), and the circle's Secretaries who joined and
left the circle; changes by adopted proposals are in their mails, the
nightly GlassFrog import announces nothing. Responses to proposals
(`mails.response_given()`): questions and comments go to the proposer,
the proposer's answers to everybody who asked or commented (also in an
earlier round, unless they left the circle), requests for
a meeting to the proposer and the circle's Secretary (else who stands
in), who prepares the meeting; consents stay silent until adopting.
Not configurable, people filter their mails; the
only setting is `User.notify_all` ("everything in all circles").

## 6. History

- **Proposals** say why: per circle, role and policy the adopted proposals
  with date, proposer, tension, meeting and diff.
- **The audit log** is the history of roles, accountabilities, domains and
  policies (`history/audit.py`): every change of a row, with who and when.
  The GlassFrog import writes the time before the app as audit rows of
  "GlassFrog" from the git history of `glassfrog.json` (`history/backfill.py`,
  about 8500 rows instead of a structure per day). Accountabilities and
  domains which no longer exist get negative IDs; texts GlassFrog didn't
  record are rows without text and render as "n accountabilities (texts
  not recorded)". The core roles' constitutional texts come from the code
  from 5.0 on (2022-12-13), the texts of 4.1 before are rows.
- **"As of" a past date** (`structure_on()`): the last audit row of every
  row up to that day, which is simpler and more reliable than replaying
  incomplete proposals.
- **`history.Change`**: the differences from day to day, computed by
  replaying the audit log (`update_changes()`, also "changed outside
  governance" in the GlassFrog period); a cache for the history pages,
  updated by `fairy_tasks` for yesterday and today, after adopting and
  after assignments (also their focus), elections, domain policies and
  strategies (`update_today()`).
- **Assignments** have `starts_on`/`ends_on`, reconstructed from GlassFrog's
  history; they are the holders of the history too. A circle's role has its
  Circle Leads and Reps as holders, GlassFrog's data missed some of them;
  the history lists the core role's assignment, not the circle's role's
  following it the same day (`views.without_following()`).
  An assignment keeps only its last term: re-elections (electing the
  holder for a new term) come from the app's elections
  (`update.reelections()`), GlassFrog's aren't known. Likewise only its
  last focus: changes of the focus come from the audit log's updates of
  assignments (`update.focus_changes()`, per day the first and the last,
  not on the day of assigning; also the nightly import's).
- The audit log covers everything else the same way, row by row.

## 7. Views

- **Circle page**: purpose, strategy, domains, accountabilities, policies
  of the super-circles (with their origin) above its own (5.2.1), roles
  with holders, sub-circles, metrics, checklists, links, pending proposals,
  meetings, due elections, history.
- **Role page**: purpose, accountabilities, domains (linking to their
  policies, which the link opens, `frontend/open_details.js`), holders with focus and
  terms (next to the name; lists of current assignments don't say since
  when, the focus is often younger: `roles/_assignment_note.html`), its policies and those of its circles (5.2.1), pending proposals
  (also for its inside), metrics, checklists, links, history.
- **Start page** (`/`, <kbd>Alt-H</kbd>): the own person page, with what
  waits for the person; the anchor circle is `/organization/` (the
  navigation's "Organization", <kbd>Alt-O</kbd>).
- **Person page**: roles grouped by circle in depth-first order, earlier
  roles; one's own also drafts, proposals waiting for a response, open
  meetings, due elections, `notify_all`.
- **Circle browser** (`/circles/`, `frontend/circles`, circle packing):
  zoom by clicking, `?circle=ID`, "My roles", colors for assigned,
  elected/core and unfilled roles with a legend, validated for light and
  dark mode. The page also lists the tree, which works without
  JavaScript; phones don't show it in the navigation.
- **Search**: roles, accountabilities, domains and policies, all terms
  matching, ignoring case and accents; snippets as plain text.
- **Export**: the whole governance as Markdown, `/export/governance.md`
  (`?holders=0` without the people); no button, `gov export` (`GET
  export/`) offers it.
- **Help** (`/help/`, `governance/help.py`): the user documentation in
  `docs/` (Markdown, also readable on GitHub: `name.md` in English,
  `name.de.md` in German, shown in the page's language) and the
  constitution in the page's language. It explains the tool, not Holacracy, and what the tool
  doesn't do (the constitution choices below).
- **404**: the search and the main pages. Drafts are the only pages which
  disappear (roles and policies are archived, people become inactive), so
  their proposer learns from the audit log when they deleted the draft and
  its tension; others see "not found", like for others' drafts
  (`governance/not_found.py`).
- **No redirects** from GlassFrog URLs (app.glassfrog.com can't redirect);
  the handbook's links are updated at the switchover using the imported
  GlassFrog IDs.
- **Modals** like Workbench's for short forms opened from a page and
  going back to it: the strategy, metrics, checklist items, links,
  policies of a domain and settings on the role's page, a holder's focus,
  a draft's tension, and a role's holders (a card
  on its page: assigning, the focus and removing, confirmed first, back
  to the page with `?next=`; a circle's page lists its roles' holders,
  changed on their pages), and the confirmations of deleting metrics,
  checklist items and links and of removing a domain's policy
  of deleting a draft or an API token and of withdrawing (`generic/confirm.html`, GET asks, POST does it). A `<dialog>` loaded by htmx
  with the `HX-Modal` header (`frontend/modal.js`,
  `governance/modals.py`), the views stay as they are:
  `generic/object_form.html` renders only the form, redirects become
  `HX-Redirect` and load the page. Escape closes changed forms only when
  pressed twice. Not for drafting roles and policies (long forms, the
  meeting has its panel).
- **Technical URLs** on purpose (`/roles/42/`), no slugs: names repeat
  (every circle has a Facilitator), change through governance (renames,
  moves) and differ in the history; the ID is what stays. Not even as
  decoration (`42-name`): links stay short and redirects don't get in the
  way of forms and htmx.

Everyone signed in reads everything except others' drafts. The Secretary
changes the circle's settings and stands in for the Circle Leads in
everything the app lets the Circle Leads do (`can_lead()`), although the
constitution doesn't say so. Superusers set things up.

The permission checks return why somebody may do something
(`roles/permissions.py`: `ALLOWED`, `AS_SECRETARY`, `AS_ADMIN`, empty
when not): what the constitution leaves to others, done as admin or as
Secretary standing in for the Circle Leads, has amber buttons with the
reason as their title (`btn-elevated`, the `button_class` tag), a note in
its form or confirmation (`generic/_right.html`), and in a meeting run
by an admin who isn't a member a note at the top. Buttons deleting,
removing somebody or withdrawing are red (`btn-destructive`, confirming
`btn-danger`); removing lines of a draft, agenda items or attendees
isn't destroying anything and stays quiet.

## 8. API

django-ninja at `/api/` (docs at `/api/docs`), the same rules as the web
interface, session or personal tokens (`APIToken`, read only or read and
write, valid until 30 days after their last use, created on the API
tokens page): `GET circles/`, `GET
roles/{id}/`, `GET search/`, `GET proposals/` (`?open=true`: the published ones of the user's
circles, nearest deadline first; each with `my_response`) and
`proposals/{id}/`, `POST proposals/` (a draft), `PATCH proposals/{id}/`,
`POST proposals/{id}/publish/`, `POST proposals/{id}/responses/` (like
the page's form: consent, meeting with the concern, comment), `GET policies/` and `policies/{id}/`, `GET domains/`, `GET export/`, `GET me/`
(the user, the token's access and their roles); objects come with the URL
of their page. Clients send instructions only (e.g. written by an LLM from
a tension); the server fills in names and returns `problems` with every
draft, the readable `changes` of the proposal's page, and for published
proposals and those waiting for a meeting the `responses` like the page
(consents and meeting requests counted, questions and concerns with their
author, `process.response_summary()`). The API only
changes the user's own drafts: the secretary amends others' proposals in a
running meeting's page, not through scripts.

`GET backup/` is the JSON backup (`backup.py`), what the token's user
sees, one file per kind: `people`, `roles` (with accountabilities and
domains), `assignments`, `policies`, `history` (the `Change`s since
2018), `proposals` (with responses, anonymous like on the page except
questions and concerns, without others' drafts), `meetings`
(with agenda, elections), `metrics`, `checklist_items`,
`links`. Lists ordered by ID with the models' field names and GlassFrog
IDs. `scripts/fetch_backup.py REPO` commits them daily to a git
repository, like the GlassFrog export before (the backlog has the rest).

The **`gov` CLI** (`cli/`, like Workbench's `wb`) is a thin client of the
API: `gov login` authorizes it in the browser (`/cli-login/`, read or
write), `gov me`, `gov circles`, `gov roles show`, `gov policies`,
`gov domains`, `gov export`, `gov search` and `gov proposals` (list, show,
create, update, publish; open, consent, request-meeting, comment). The Claude Code skill `governance-proposal`
(`cli/skills/`) prepares a draft from a tension with it; publishing stays
the user's decision.

## 9. Import from GlassFrog

`./manage.py import_glassfrog ~/projects/glassfrog`, idempotent (by
`glassfrog_id` and date):

1. Users (see section 2), created with German as their language (they
   change it on their page); `settings.ADMINS` become superusers.
2. The current structure of live circles from the newest files.
   Circles with only core roles become roles (`normalize()`).
3. Proposals, tensions and meetings. Adopted proposals keep their
   instructions with GlassFrog IDs (`Proposal.glassfrog_id` tells them
   apart), they are history; names are resolved against the last snapshot
   before `accepted_at` or the proposal's own `add` instructions. Open
   proposals (drafts, published, waiting for a meeting) get the app's IDs
   (`to_app_ids()`), objects they add keys like `n1`: the app adopts them.
4. Assignment history, the history as audit rows (replacing the import's
   own audit rows of the structure) and `Change`s from the git history of
   `glassfrog.json`. Its last day is the database's state
   (`structure_from_database()`), so the audit log continues without
   spurious changes. Nightly imports' changes are audit rows themselves.
5. Mentions become `@[Name](role:ID)` (longest name in the circle and its
   super-circles, also earlier names); the import lists unresolved ones.

`import_glassfrog --api` fetches today's state with `GLASSFROG_TOKEN` and
adds it to the history in the database, so the server needs no checkout:
vanished roles and policies are archived today, assignments start and end
today, users are linked by `glassfrog_id` (redacted people who left).
It runs nightly until the switchover.

## 10. Constitution choices

Decided differently:

- **Async proposals are adopted at their deadline** even when their
  proposer no longer fills the proposal's role (5.3.1 is checked when
  publishing and in meetings): the circle had its chance to object.
- **The deadline of async proposals** (`async_acceptance_days`, 5.3)
  changes a default process, so by 5.2.1 a policy setting it applies
  only in its own circle unless it says so. The app treats the anchor's
  setting as applying to all sub-circles (each may set its own), like
  our anchor's policy; its wording has to say so.

Deliberately not modelled:

- **The Circle Lead** stays as defined (1.4.5): no accountabilities or
  domains added through governance (they would apply to every
  sub-circle's Circle Lead), no delegation removing them. The
  documentation has to say so. Neither do Facilitator, Secretary and
  Circle Rep get any (1.3.3, 5.1.1 would allow it; decided 2026-11-07):
  their holders would set the policies of such domains, and our data has
  none.
- **Linked roles** (1.3.4): no demand in our data, much complexity.
- **Redirecting references** from outside the circle (1.4.4): an edge
  case, a proposal in the circle containing the reference does the same.
- **Relational agreements** (2.4), **asking for permission** to impact a
  domain or announcing spending (4.1.2, 4.1.3), **explaining individual
  initiative** (4.3): communication between people, in the chat or
  the task management tool.
- **Election policies** (5.1.1, 5.1.2): policies widening the
  candidates beyond the members or allowing several Circle Reps; the app
  always elects among the members and one Rep.
- **Special governance meetings** (5.4): a meeting requested for a
  stated intent, limited to certain changes; the request goes into the
  calendar and the notes, the app doesn't limit what it adopts.
- **The anchor circle's own governance** (1.3.3): the constitution only
  lets the anchor change its purpose and clarify its accountabilities,
  by policy; here the board of directors decides, the app lets the
  anchor's governance change its definition directly, the audit log
  records it.
- **Guests of Circle Reps** (5.3, 5.4.1) don't propose or object
  themselves, the inviting Rep does for them.
- **Meetings ending by inactivity after midnight** record their steps
  (e.g. a circle turning back into a role) on the day they end; people
  end meetings explicitly.
- **Process breakdowns** (5.5): rare; the super-circle's Facilitator
  stands in, an admin assigns an additional Circle Lead, the declaration
  goes into the notes.

## Backlog

- **Non-core members of a role** (later, not yet): people taking part in
  a role's inner circle (its proposals and governance meetings) without
  holding the role; today its members are only its holders (`members()`).
- **Before the switchover** (assessment of 2026-11-07; GlassFrog stays
  the source of truth until then, so bugs cost little now):
  - Another verification round or two: each round so far still found
    bugs combining features.
  - One or two real meetings in the app, also to see the mails in real
    clients (several role mails at a meeting's end since elections are
    announced then).
  - Only adopting takes `lock_structure()`; assignments, domain policies
    and elections at the same moment are untested.
  - Recomputing the whole history (reinitializing, the import) at the
    real size isn't measured.
  - The lists of current assignments (focus and term next to the name)
    haven't been looked at in the browser (light and dark, long focus
    texts, narrow screens).
- **Next deploy**: not while a governance meeting which recorded
  elections runs: elections before migration `meetings.0006` lack the
  data to undo them, a correction or the meeting's end would end the
  wrong assignment or announce wrongly. Remove this item afterwards.
- **Switchover**: a final import, update the handbook's links, cancel
  GlassFrog, then stop the nightly `import_glassfrog --api`. Run
  `scripts/fetch_backup.py` daily on the fetcher's server (with a read
  only token) instead of `fetch_glassfrog.py`, into a new repository: to
  consider then or afterwards, converting the GlassFrog export's commits
  into the backup's format. Let the
  open imported proposals be adopted async too (`adopt()` refuses
  proposals with a `glassfrog_id` outside of running meetings until then,
  e.g. at GlassFrog's deadlines; until then the app's async process moves
them to "waiting for a meeting" at the last consent or the deadline, and
the nightly import sets them back: accepted, decided 2026-11-06; it also
overwrites the status and amendments of one on the agenda of a meeting
running at 03:00, i.e. active after midnight: accepted too, decided
2026-11-07). Remove
  "Until the switchover" from `docs/README.md` (and `README.de.md`) and the notes about GlassFrog
  being the source of truth in `AGENTS.md` and this file.
- **Published interpretations** (4.2.1): the Secretary's rulings, binding
  for the circle and its sub-circles, shown on the circle page. Postponed,
  we never had the case.
- **Django Tasks** for jobs which belong to a moment, not a schedule:
  ending a meeting when its inactivity runs out (instead of the hourly
  `end_inactive_meetings`), sending mails outside the request.
- **PDF export**, if needed.
- **Modals** for more forms where they help.
