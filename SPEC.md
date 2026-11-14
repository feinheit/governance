# Spec: Governance (replaced GlassFrog)

A Django app which replaced GlassFrog: circles, roles, accountabilities,
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
(light and dark mode), django-ninja, the daily `fairy_tasks` and `hourly_tasks`, German
first. htmx 4 on the meeting page and for the modals, a Preact island for
the circle browser,
all styles and scripts in one bundle (rspack, only the parts of Bootstrap
in use).
Hosted at `governance.feinheit.ch` (see `AGENTS.md`).

Our governance data never goes into this repository: tests and examples
use made-up circles, roles and people.

## 1. GlassFrog data

`feinheit/glassfrog` (`~/projects/glassfrog`) was fetched daily until the
switchover (`scripts/fetch_glassfrog.py`, in the git history); the app
imported it, section 9. It explains the imported history. Urs and Dan set
up these daily dumps in November 2018 for a visualization of the circles
(Workbench project 2018-0700 "Hola Circle Viz"), Dan wrote the export
script, the cron job and its error mail: the structure's history since
then comes from their git history (section 6).

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
  sub-circles' Role Leads missing in the super-circle.
- Roles without people are held by the Circle Leads.
- The API shows people who left as "Removed" with a redacted email; the
  snapshots still have their names.

**The other files** (since 2026-11-04): `roles` (accountability texts),
`assignments` (focus, election term), `policies` (also those of roles for
their domains), `proposals` (1281, with tensions and instructions),
`tensions`, `governance_meetings`, `tactical_meetings` (agenda labels only,
no outcomes), `metrics`, `checklist_items`, `projects`. 257 governance
meetings (2018–2022) and 617 tactical meetings (2018–2023) have no circle
(`links.circle` is null, without proposals to infer it from): imported
without one, they belong to no list. GlassFrog's tactical meetings have
no invited roles, so tactical meetings without a circle in the app are
the ad hoc ones called here.

**Proposal instructions** are JSON-patch-like with old values:

```json
{"op": "replace", "path": "/roles/123/accountabilities/456/description",
 "original_value": "Planning workshops", "value": "Planning and running workshops"}
```

Ops `add`, `replace`, `remove`, `move` and `test` (the target must still
exist; only roles and policies, not their fields). Paths cover roles (`name`, `aim` = purpose, `supporting_circle` =
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
  and removed with their circle, governance adds no accountabilities or
  domains to them (see the constitution choices). `archived_on` instead of deleting, `other_names` (earlier
  names, texts may mention them), `is_elected_by_policy`,
  `async_acceptance_days` (inherited by sub-circles; the anchor's policy
  says 4 days, one circle uses 1; GlassFrog has no setting for it, the
  import set our anchor's 4 days on the anchor circle unless set here;
  without any, the constitution's default: no time limit, async proposals
  without a deadline are adopted once everybody consented, 5.3), `glassfrog_id`/`glassfrog_circle_id`.
  The policies stay the explanation of these settings, the Secretary sets
  them on the "Settings" pages.
- **`Accountability`**, **`Domain`**: `role`, `text`, `position`. Their
  order isn't governance: anybody drags them into an order on the role's
  page (arrows without JavaScript, `roles/editing.py`), without a proposal
  or a mail; the audit log keeps it, the history doesn't count it as a
  change (decided 2026-11-09).
- **`Policy`**: `role` (the circle, or a role for its domains), `title`,
  `body`, optional `domain`, `archived_on`.
- **`Assignment`**: `role`, `user`, `focus`, `elected_until`, `starts_on`,
  `ends_on`; ending keeps the row. A person holds a role once (a
  constraint), the focus lists everything; the import merged GlassFrog's
  assignments per focus. Circle membership isn't stored: the
  Role Leads of a circle's roles plus the Circle Leads and Circle Reps of its
  sub-circles (`permissions.members()`).
- **`Metric`**, **`ChecklistItem`**: `role`, `whole_circle` (a role
  reports its items in its circle's tactical meetings, a sub-circle like
  any role, GlassFrog's items of a sub-circle's role; a circle's own items,
  reported by the whole circle in its own meetings, are `whole_circle`,
  so nothing changes when a role becomes a circle, a circle turning back
  into a role reports them itself; `RoleItem.reported_in`, decided
  2026-11-14, issues #2 and #3),
  `description`, `frequency` (weekly, monthly, quarterly, yearly or none;
  only groups them), `link`. Operational: the Circle Leads of the circle
  reviewing them edit metrics, anybody edits checklist items (Holacracy
  defines no process), the audit log keeps their history. A circle's page
  lists its roles' items too and those its sub-circles report in it; the
  form's "Reported by" (`editing.reporters()`) chooses among the circle
  itself, its roles (a sub-circle reporting in it, grouped) and the circle
  in its super-circle; a role's page only the role in its circle (and the
  whole circle's, if a role's item has it already, `role_reporters()`).
  Adding on a circle's page chooses explicitly (empty at first, no
  default; the constitution's reviews are of what participants report
  "for their Roles", 3.2, the whole circle's is GlassFrog's convention). The import mapped GlassFrog's items of a sub-circle's role
  to the sub-circle's own, fixed by hand after the switchover.
  GlassFrog's "global" items, shown everywhere, aren't supported; items
  without circle and role belong to the anchor.
- **`Link`**: `role`, `title`, `url`, `description`; anybody edits them.
- **`Note`**: `role`, `title`, `body` (Markdown); GlassFrog's notes
  (its API v5, the v3 export had none) were added after the switchover
  with `gov notes`. Like links, anybody edits them,
  the audit log keeps them, the history shows them on request, no mails
  (decided 2026-11-12). A core role's notes stay with it (a Circle
  Lead's), they aren't moved to the circle. Links and notes are one
  card on the role's page, one list anybody orders (they share their
  `position`, new ones last: `editing.references()`).
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
(GlassFrog's format), `names` (for rendering), `status`, `published_at`,
`deadline`, `decided_at`, `meeting`, `glassfrog_id`,
`adopted_in_glassfrog` (its instructions keep GlassFrog's IDs, set when
imported). No kind: the
policies of domains are recorded as adopted proposals (titled by what
they change), spelling goes through governance (decided 2026-11-08).

GlassFrog's format made the import 1:1, every proposal a readable diff,
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
also when no meeting is running. Three months after it started waiting
(`waiting_since`, restarted when a meeting it was on ends) it goes back to
its proposer's draft with a mail, unless a meeting not ended has it on its
agenda (`process.expire_waiting()` in `fairy_tasks`, decided 2026-11-13:
the list of waiting ones shouldn't only grow; those whose proposer left are
withdrawn). Escalated GlassFrog proposals older than
two months (published, else created) and not on an agenda were
imported as drafts: their proposers bring them again or delete them, admins
can't withdraw other people's proposals. Open proposals imported from
GlassFrog are processed like the app's own since the switchover, adopted
async at their GlassFrog deadline: nobody resubmits a proposal nobody
objected to (decided 2026-11-08; GlassFrog's responses weren't imported). Drafts are private to the proposer until published
or brought into a meeting; a draft without changes is a tension (`Proposal.has_changes`: a `test` alone only checks that a role or policy exists; the API drops tests of subjects it doesn't change, like the forms, `drafting.normalize()`) (the
tension inbox; GlassFrog's open tensions were imported as such). New
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
with it (decided 2026-11-07). A proposal's page and the meeting list
its changes grouped by role and policy, with icon buttons editing the
role or policy in the proposal and discarding all its changes, confirmed
in a modal (decided 2026-11-09; the buttons under the first change only
were unclear). Removing a circle moves the
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
  Role Leads propose in the role, adopting makes it a circle with them as
  Circle Leads; proposals from the role itself then come from its Circle
  Lead role (e.g. the next ones of the same meeting, decided
  2026-11-07). With a single Role Lead publishing adopts right away. Only
  the Role Leads get the mails, not the circle containing the role: its
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
  domains stay the role's, its Role Leads change them again. Drafts say so beforehand, the
  adopted proposal records the steps. A role made a circle on purpose
  (without roles yet) stays one, also when its first meetings end
  without adding any: only a proposal emptying it turns it back.

**Async proposals**: circle members get a mail with the tension and the
diff. Publishing checks again that the proposer may propose from the
proposal's role (5.3.1), e.g. their assignment ended since drafting;
drafts without a role (a guest's item drafted again, drafts imported
from GlassFrog) get one first (decided 2026-11-07). Until the deadline (`async_acceptance_days`) members ask questions
(comments), consent ("no objection", without a text: it's only counted,
a text is refused rather than dropped; the form chooses nothing
beforehand and shows the text field only for questions and requests,
`shown_for.js`, decided 2026-11-07) or request a meeting, optionally with
the concern, which moves it to the next governance meeting. No async
objections, like GlassFrog: objections are tested in meetings, so async is
for uncontroversial changes. The proposer only answers questions. Adopted
when everybody else consented, or by the hourly task (`hourly_tasks`)
after the deadline; pages and mails show the day, not a time
(`adopted_on`: the deadline's day, unless it's after the day's last run;
hourly since 2026-11-10, before nightly). Due proposals are
adopted in order of publication. Adopting a proposal (async or in a
meeting) rechecks the open ones (`process.recheck_conflicts()`, also
nightly for changes outside proposals such as domain policies, decided
2026-11-13): those it conflicts with are marked (`Proposal.conflicting`,
a red "conflict" badge in the lists, the problems on the page and in the
API, cleared when saving them merged), published ones go back to their
proposer's draft at once with a mail to the circle (the consents were to
a proposal which can't pass; no new state). One still failing at its
deadline or last consent (e.g. its role left) goes to the meeting.
Adoptions run one after the other (`locking.lock_structure()`, an
advisory lock until the transaction ends), so that two at once check
against each other's changes; so do the views changing assignments,
domain policies and elections around the process (`locking_structure`,
POSTs take it before loading anything, the request's transaction holds
it, `ATOMIC_REQUESTS`).
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
`roles` and `policies` (also drafts', for the proposals' filter by
role) those the instructions change now, also when
brought into or amended in a meeting; `adopt()` adds those it creates or
defers. The weekday restriction of one circle's policy stays a soft
rule.

**Outside the process**, recorded for the history:

- **Policies of a domain's role** (1.3.2, `roles/domain_policies.py`):
  the role's Role Leads (the Circle Leads while unfilled) add, change and
  remove its policies on the role page, each with one of its domains.
  Every change is recorded as an adopted proposal (the history says
  "Changed directly", `Proposal.is_direct`), mailed to the
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
  assigned this way. Role Leads resign through their Circle Leads, who end
  assignments of elected roles too ("Role Leads" on the role's page;
  `can_end_assignment()`, a Rep's hold of the circle's role ends with it).
- **Circle Leads**: a circle may have several, each with all the rights
  (texts speak of Circle Leads). While nobody holds a circle's Circle
  Lead role (its role in the super-circle), the super-circle's Circle
  Leads lead it, recursively (1.4.2, `permissions.circle_leads()`):
  they assign, propose from its unfilled roles and are its members. The
  same for a role nobody holds: its circle's Circle Leads are its
  Role Leads (`role_leads()`), also for its inner circle. The anchor circle
  has Circle Leads only when assigned. Archived circles and roles have
  nobody: archiving ends their assignments, and nobody from above fills
  them in. Facilitator and Secretary follow
  the constitution's stand-ins (5.3.6); the app gives them no rights in
  meetings the other members don't have, except the secretary amending. An
  assignment removed on the day it started was a mistake and is deleted.
  Adopted proposals record whose assignments they ended
  (`Proposal.ended_role_leads`), so that the meeting's outputs reach them
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
meetings and the circle's page lead to the running one instead), the Role Leads of a role a governance meeting
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
usual): hourly (`hourly_tasks`) and when
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
Circle Leads like other unfilled roles, not a role to propose from, nobody invited with it to ad hoc tactical meetings). A circle may decide
to go without one: electing nobody (the Circle Rep only, `Election.user`
and `term_ends_on` empty) ends the Rep's assignment. Re-electing changes the term, electing somebody else
ends the previous assignment (removed if it only started today), a Rep
also holds the circle's role in the super-circle. Elected roles have one
Role Lead: recording the same role again in the meeting (a correction, a
second vote) replaces the earlier result, undone first (`Election`
keeps what it changed: the previous Role Lead keeps their assignment). Due elections (within 14 days, decided 2026-11-09: acting a few days or weeks beyond the term is fine; nobody elected except for the Circle
Rep, which may stay unfilled, or held without a term, e.g. a role made elected by policy while held; terms end in the
future) are marked with a badge "election due" in the circle's lists of
roles (core roles and roles) and on the person pages of who holds them
(decided 2026-11-09: no card of its own, the Facilitator's and
Secretary's person pages listed elections they weren't concerned
with), and are
on the agenda of a governance meeting when it starts (like GlassFrog: one
plain item per role, "Election: Secretary", owned by the Facilitator or who
stands in; the election is recorded in the Elections card);
Facilitators (5.3.5; else Secretaries, else Circle Leads) get a mail
on Mondays.

**Tactical meetings** (article 3): any circle member
starts a regular one (all roles of the circle invited, attendees its
members); anybody calls an ad-hoc one from the user's menu (`tactical_call`): the
roles of any circles first (a field filters them as you type,
`frontend/filter_rows.js`, also by the Role Leads' focus), then who of their Role Leads attend (with their focus), all
checked, some unchecked to narrow the invitation (3.1); the caller fills one of the roles at least (also as Circle Lead of an unfilled one, 1.4.2), else the roles are chosen again, and attends (not uncheckable). Ad hoc tactical meetings (without a circle) have
a badge of their own, hollow and dashed ("Ad hoc Tactical Meeting",
`Meeting.is_ad_hoc`). Steps: check-in, checklist review, metrics review (the
invited roles' entries, for regular ones also the circle's own, not a
sub-circle's whole circle's), progress updates (the links of the circle and the
invited roles, the outcomes and links of the circle's last three
tactical meetings having some, "Show earlier meetings" ten, then ten
more, `?earlier=`, which the page's updates keep; `progress_context()`),
agenda, processing tensions,
closing. An item may record an outcome and a link, both optional, saved
while the secretary types (`data-autosave`, `X-Autosave`, the others
see it with their next update; "Save and done" completes the item): many
items end with information, next actions and projects live in the task
management tool (several of them are one link to a to-do list; the
outcome mentions the role taking them on, `@`, rendered like other texts
with mentions, the mail with the roles' names), and a
governance tension is captured by its owner as a tension of their own
(the app doesn't add tensions for others). GlassFrog's actions and
projects weren't imported; the circles got the projects as Markdown to-do
lists for their task management tools at the switchover.
Open meetings are listed on the attendees' person pages.

## 5. Notifications

`docs/mails.md` lists them for the users (when, to whom); keep it up to
date with this section. Every mail greets the recipient by their first
name ("Hallo Ada,", copies "Hallo,") and ends with a link to that page
(`mails._send()`).

Plain text mails per active recipient in their language (none for
people who left, also as proposers), after the transaction commits (`notifications/mails.py`), to the circle's members: published
async proposals, those taken back, those their proposer withdraws
(published or waiting for a meeting, `process.retract()`), those which
can't be adopted async and wait for a meeting (a problem at the
deadline or the last consent, `mails.proposal_to_meeting()` with the
problems), those back to the draft because a proposal adopted meanwhile
conflicts (`mails.proposal_conflicting()`, with the problems; those
waiting three months only to their proposer, `mails.proposal_expired()`), adopted ones with the diff (also to
the proposer, and to the members before adopting, e.g. the Role Leads of
roles the proposal removes or moves away, and the Secretaries, who
invite them to meetings, and Circle Leads of the sub-circles it moves
roles or policies into or out of, `mails.moved_between()`), domain policy changes (section 3), strategy changes (to the members of the circle and its sub-circles, like domain policies; each save, merging quick edits is for later), and when a meeting ends
its outputs (adopted proposals, elections, notes, tactical outcomes;
also to the attendees and, like adopting async, the Role Leads of roles
the adopted proposals changed, removed or moved away, also deeper inside:
roles of a removed circle, core roles of a circle turned back, and the
sub-circles' Secretaries and Circle Leads like adopting async). A
circle emptied by its super-circle while its own meeting ran turns back
when that meeting ends: those losing its core roles get the mail about
their roles then. Like GlassFrog, assignments, removals, elections
and deactivations (`notifications.role_leads.announce()`; elections when the
meeting ends, the results after corrections only, not those of core
roles archived by the circle turning back then (the outputs list them,
"the role doesn't exist anymore", decided 2026-11-07):
`elections.announce_elections()`, decided 2026-11-07) tell people the roles
they get (with their focus) and lose (not the circle's role in the super-circle, which
follows the core roles), and the circle's Secretaries who joined and
left the circle; changing a Role Lead's focus tells the Role Lead
(`mails.focus_changed()`, nobody else, decided 2026-11-07). Assigning, removing, changing the focus and a role's policies for its domains name who did it ("Ada assigned you the role Cook in Kitchen.", "Changed by Ada."), not to themselves; elections and deactivations name nobody (decided 2026-11-11). Changes by adopted proposals are in their mails. Responses to proposals
(`mails.response_given()`): questions and comments go to the proposer,
the proposer's answers to everybody who asked or commented (also in an
earlier round, unless they left the circle), requests for
a meeting to the proposer and the circle's Secretary (else who stands
in), who prepares the meeting; consents stay silent until adopting.
Not configurable, people filter their mails; the
only setting is `User.notify_all` ("everything in all circles").
`MAIL_COPIES` (a list of addresses, in the environment) get one copy
of each mail (one per mail sent to several people with the same text,
saying to whom: "Copy of the mail to Ada, Bob."; personal mails like
roles changed one per person; in the language of their account, else
the default), not when they received it themselves (compared by
address), as Cc without a To to make filtering easy. Temporary, to
verify the mails; removed once they've proven themselves.

## 6. History

- **Proposals** say why: per circle, role and policy the adopted proposals
  with date, proposer, tension, meeting and diff.
- **The audit log** is the history of roles, accountabilities, domains and
  policies (`history/audit.py`): every change of a row, with who and when.
  The GlassFrog import wrote the time before the app as audit rows of
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
  strategies (`update_today()`). One row per accountability or domain
  added or removed; the pages merge a role's of a day into one entry
  ("Accountabilities changed", `views.merge_lists()`), like the proposal
  which made them, texts replaced by similar ones as a diff (`pairs()`,
  the most similar first).
- **Assignments** have `starts_on`/`ends_on`, reconstructed from GlassFrog's
  history; they are the Role Leads of the history too. A circle's role has its
  Circle Leads and Reps as Role Leads, GlassFrog's data missed some of them;
  the history lists the core role's assignment, not the circle's role's
  following it the same day (`views.without_following()`).
  An assignment keeps only its last term: re-elections (electing the
  Role Lead for a new term) come from the app's elections
  (`update.reelections()`), GlassFrog's aren't known. Likewise only its
  last focus: changes of the focus come from the audit log's updates of
  assignments (`update.focus_changes()`, per day the first and the last,
  not on the day of assigning).
- **Links, notes, metrics and checklist items** are changes too (`link-added`
  etc., `diff_items()`), operational: the history shows them on request
  (right away, `update_today()` on the pages and in the API), the role's
  page not.
- **Filters** like Workbench's (`governance/filters.py`,
  `generic/_filters.html`, `frontend/filters.js`: GET forms submitting when
  changed). The history is one page (`/history/`, `?role=`): a circle
  with its roles (a sub-circle as a role; "With sub-circles" with what's
  inside them; today's roles, whose past moved along with them, those
  which left show their move, decided 2026-11-08) or a role alone (a
  former circle with its roles coming, going and moving out, not their
  history), with assignments, with links, notes, metrics and
  checklists; links to a day (`?day=`) open its page. A policy's page has
  its own history (its changes, the adopted proposals changing it), the
  days linking to its role's. The proposals by status,
  circle (with its sub-circles) and the role they change; the meetings of a circle or role by kind (governance, regular tactical,
  ad hoc tactical).
- The audit log covers everything else the same way, row by row.

## 7. Views

- **Roles show their purpose, domains and accountabilities in this order**
  everywhere: the pages, "as of", the export, `gov roles show`, the
  drafting forms (and the instructions they make), the admin.
- **Lists of meetings** tease what they were about (`meetings/teasers.py`):
  the adopted proposals of governance meetings, else the agenda items,
  three of them and how many more.
- **Circle and role pages** are laid out for the desktop: on the left
  what the role is (purpose, domains, each with a button adding a policy
  for it, accountabilities, its own policies if it has any), on the right what is used most (Role Leads or core roles, a
  circle's meetings, pending proposals), then checklists,
  links and history; a circle's roles below both. What constrains it
  from outside is in the menu "…", in a modal ("Domains and policies
  affecting this role", `role_context`): per circle from the anchor circle down,
  the circle's domains and policies (5.2.1) and the domains of its roles
  with their policies (1.3.2; e.g. a role of the anchor circle holding
  the laptops). A running
  meeting has a button in the header. A role's governance meetings (for its inside, 1.3.1) are rare, its menu starts them and links its meetings (a circle's menu too, besides its Meetings card: easier to find), also the ad hoc tactical meetings it was invited to and a role's those of its circle, which invite all its roles (since it moved into the circle, if it did; `Meeting.objects.of_role()`; GlassFrog's tactical meetings have no invited roles; a circle's list has its own, not its super-circle's).
- **Circle page**: purpose, strategy, domains, accountabilities, its
  policies, core roles (due elections marked), meetings, pending proposals,
  checklists and metrics (two cards, like the tactical meeting's two steps,
  with those of its roles), links, notes, history, roles with Role Leads and sub-circles.
- **Role page**: purpose, domains (linking to their
  policies, which the link opens, `frontend/open_details.js`), accountabilities, its policies, Role Leads with focus and
  terms (next to the name; lists of current assignments don't say since
  when, the focus is often younger: `roles/_assignment_note.html`), pending proposals
  (also for its inside), checklists, metrics, links and notes (one card,
  notes folded, `#note-ID` unfolds one), history (its former
  names, the latest proposals and changes without the assignments and
  the counts of texts not recorded, `recent_history()`: GlassFrog
  renamed many roles without a proposal).
- **Start page** (`/`, <kbd>Alt-H</kbd>): the own person page, with what
  waits for the person; the anchor circle is `/organization/` (the
  navigation's "Organization", <kbd>Alt-O</kbd>).
- **Navigation**: Organization, Circles, People (from the `lg`
  breakpoint on, small screens have it in the menu only), Proposals,
  History and the search; the user's name opens a menu with their page, calling a tactical
  meeting (not tied to a circle or role), People, Mail addresses, Help,
  API and signing out. The menus "…" of circles and roles list the
  meetings first.
- **Mail addresses** (`/people/addresses/`, `roles/addresses.py`): to
  copy (`frontend/copy.js`) or to write to ("New mail", `mailto:`):
  everybody holding a role, all Circle Leads, Facilitators and
  Secretaries (unfilled ones: who stands in, like for the reminders of
  elections and `acting_secretaries()`), Circle Reps, and each circle's
  members (its menu links them). Names as they are, quoted when needed,
  not encoded for headers.
- **Members of a circle** (`/roles/<pk>/members/`, the circle's menu
  "…"): a matrix of its roles (core roles first) and its members
  (`permissions.members()`, the columns), filled where somebody holds the
  role, hollow where the Circle Leads hold an unfilled one
  (`role_leads()`), then the active people who aren't members (also
  those without roles) as columns on the right, to assign them directly.
  It fills the window below its top (`fitFlow()`) with the names and the
  roles sticky. Hovering over or focusing a cell shows its tools in a
  bubble (CSS only) where allowed: assign the person (`?user=` preselects
  them), edit the focus, remove; in modals, back to the matrix. A matrix
  of the whole organization breaks down beyond a few dozen people
  (decided 2026-11-11).
- **Person page**: roles grouped by circle in depth-first order, earlier
  roles (due elections marked); one's own also drafts, proposals waiting
  for a response, open meetings and the settings.
- **Settings** (`/accounts/settings/`, a modal from the menu with one's
  name and from one's page): name, short name, language (required:
  without one pages follow the browser but mails are German; preselected
  the page's) and mails (`notify_all`) in one form with one save button;
  the mail address shown but disabled, Google sign-in matches it
  (decided 2026-11-08).
- **Circle browser** (`/circles/`, `frontend/circles`, circle packing):
  zoom by clicking, `?circle=ID`, "My roles", colors for assigned,
  elected/core and unfilled roles with a legend, validated for light and
  dark mode. The path and "My roles" beside the page's title, the legend
  beside the circle from 992px on (screens are rather wide than tall),
  no explanation above it. The circle is as high as the window allows
  below its top (measured like the meeting's columns, `fitFlow()`) with
  the list's header still visible, and narrow enough for the legend
  beside it. The page also lists the tree, which works
  without JavaScript.
- **Search**: active people first (name, short name and mail address;
  with the circles whose roles they hold), then
  roles, accountabilities, domains, policies and links (title and
  description, which may hold keywords: rules for people as employees
  live in the handbook, not in policies, and are found through links of
  the roles keeping them) and notes (title and body, opening the note on
  its role's page), checklist items and metrics (their descriptions,
  leading to the role reporting them), all terms matching,
  ignoring case and accents, in the texts as the pages show them
  (mentions with the current names, the core roles' constitutional
  texts); snippets as plain text. The API and `gov search` too.
- **Export**: the whole current governance as Markdown (circles, roles,
  their texts, policies, metrics, checklist items, links and notes), `/export/governance.md`
  (the people only with `?people=1`, `--with-people`: personal data
  is opt-in, decided 2026-11-08); no button, `gov export` (`GET
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
  the handbook's links were updated at the switchover using the
  imported GlassFrog IDs.
- **Modals** like Workbench's for short forms opened from a page and
  going back to it: the strategy, metrics, checklist items, links, notes,
  policies of a domain and settings on the role's page, a Role Lead's focus,
  a draft's tension, and a role's Role Leads (a card
  on its page: assigning, the focus and removing, confirmed first, back
  to the page with `?next=`; a circle's page lists its roles' Role Leads,
  changed on their pages), and the confirmations of deleting metrics,
  checklist items, links and notes and of removing a domain's policy
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
roles/{id}/` (core roles with the constitution's texts, without IDs; with its links, notes, metrics and checklist items), `POST roles/{id}/links/`, `PATCH links/{id}/` and `DELETE links/{id}/`, the same for `notes` (anybody, of active roles, like on the pages), `POST roles/{id}/metrics/` and `roles/{id}/checklist/`, `PATCH` and `DELETE items/metrics/{id}/` and `items/checklist/{id}/` (`role_id` and `whole_circle` move them; metrics need the Circle Leads of the circle reviewing them, before and after), `GET
roles/{id}/context/` (the role's page's context, `roles/context.py`), `GET constitution/`, `GET search/`, `GET proposals/` (`?open=true`: the published ones of the user's
circles, nearest deadline first; each with `my_response`) and
`proposals/{id}/`, `POST proposals/` (a draft), `PATCH proposals/{id}/`,
`POST proposals/{id}/publish/`, `POST proposals/{id}/responses/` (like
the page's form: consent, meeting with the concern, comment), `GET policies/` and `policies/{id}/`, `GET domains/`, `GET export/`, `GET me/`
(the user, the token's access and their roles); objects come with the URL
of their page, times in local time (their first ten characters are the
day the pages show), proposals with `adopted_on`. Clients send instructions only (e.g. written by an LLM from
a tension); the server fills in names and returns `problems` with every
draft, the readable `changes` of the proposal's page, and for published
proposals and those waiting for a meeting the `responses` like the page
(consents and meeting requests counted, questions and concerns with their
author, `process.response_summary()`). The API only
changes the user's own drafts: the secretary amends others' proposals in a
running meeting's page, not through scripts.

`GET backup/` is the JSON backup (`backup.py`), what the token's user
sees, organized by role (decided 2026-11-08): `roles`, all of them
(archived ones too) ordered by ID, each with its circle's ID,
accountabilities, domains, policies (archived ones too, each with its
history), `role_leads` (the assignments, past ones too), metrics,
checklist items, links, its `history` (the `Change`s since 2018) and,
as the circle of, its `proposals` (with responses, anonymous like on the
page except questions and concerns, also earlier consents with a text,
without others' drafts) and `meetings` (with agenda, elections);
`meetings` without a circle (ad hoc tactical meetings); `people` only
with `?people=true`, the rest refers to them by ID. The models' field
names and GlassFrog IDs. `gov backup DIR --with-people` writes a file
per role named by its ID (`roles/<id>.json`: a renamed role keeps its
file, `git log roles/34.json` shows its whole life, decided 2026-11-08),
`meetings.json`, `people.json` and `governance.md` (the Markdown export,
to read; its daily diff reads like a changelog). Each run replaces the
files: `roles/` is emptied first, `people.json` removed without the
people. `scripts/fetch_backup.py REPO` runs it and commits everything
daily (`git add --all`) to a git repository, like the GlassFrog export
before (the backlog has the rest). Stable order for small diffs: lists by ID (moving or
reordering changes a field), the history by day, keys sorted;
`governance.md` in the organization's order with the ID breaking ties
(the Markdown has no date: the download's file name has it).
The current state for reading is the Markdown export, exact IDs come
from `gov search --json` and `gov roles show --json`.

The **`gov` CLI** (`cli/`, like Workbench's `wb`) is a thin client of the
API: `gov login` authorizes it in the browser (`/cli-login/`, read or
write), `gov me`, `gov circles`, `gov roles show`, `gov policies`,
`gov roles context`, `gov domains`, `gov export`, `gov backup`, `gov constitution`, `gov search`, `gov links`, `gov notes`, `gov metrics` and `gov checklist`
(list, add, update, remove) and `gov proposals` (list, show,
create, update, publish; open, consent, request-meeting, comment). The Claude Code skill `governance-proposal`
(`cli/skills/`) prepares a draft from a tension with it; publishing stays
the user's decision. `governance-review` reviews a circle's or a role's
governance against the constitution (`gov constitution`), read only.

## 9. Import from GlassFrog

Until the switchover `./manage.py import_glassfrog` imported the export
(section 1) and, nightly, today's state from GlassFrog's API; the importer
(`governance/glassfrog/`) is in the git history, removed after the
switchover, when the app became the source of truth. It imported:

1. Users (see section 2), with German as their language.
2. The structure of live circles; circles with only core roles became
   roles.
3. Proposals, tensions and meetings. Proposals adopted in GlassFrog keep
   their instructions with GlassFrog IDs (`Proposal.adopted_in_glassfrog`),
   they are history; open ones got the app's IDs. Those without a tension
   (most elections) are titled after all they change (`summarize()`:
   "Election: Facilitator, Secretary", "Baker: Name, Purpose").
4. The assignment history and the history since 2018 as audit rows of
   "GlassFrog" (`history/backfill.py`, whose format `audit.structure()`
   reads), continued without differences by the app's audit log
   (`structure_from_database()`).
5. Mentions as `@[Name](role:ID)`.

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
  sub-circle's Circle Lead). The documentation has to say so. Neither
  do Facilitator, Secretary and Circle Rep get any (1.3.5, 5.1.1 would
  allow it; decided 2026-11-07): their Role Leads would set the policies
  of such domains, and our data has none.
- **Delegating the Circle Lead's authority** to another role or process
  by policy (1.4.5, e.g. how a role is assigned, 1.4.1) is allowed by
  the constitution, but not implemented: no current use case (decided
  2026-11-09). Such a policy stays text; the Circle Leads (or the
  Secretary standing in) still record the assignments in the app.
- **Linked roles** (1.3.4): no demand in our data, much complexity.
- **Redirecting references** from outside the circle (1.4.4): an edge
  case, a proposal in the circle containing the reference does the same.
- **Relational agreements** (2.4), **asking for permission** to impact a
  domain or announcing spending (4.1.2, 4.1.3), **explaining individual
  initiative** (4.3): communication between people, in the chat or
  the task management tool.
- **Election policies** (5.1.1, 5.1.2): policies widening the
  candidates beyond the members, limiting them (e.g. no Circle Lead as
  Facilitator) or allowing several Circle Reps; the app always elects
  among the members and one Rep (confirmed 2026-11-09). Circle Leads may
  be elected Facilitator or Secretary, only not Circle Rep (5.1.1; 4.1
  excluded the Lead Link from Facilitator too, 5.0 doesn't).
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
  holding the role; today its members are only its Role Leads (`members()`).
  Then revisit `can_add_items` (`meetings/access.py`): whoever holds an
  invited role adds items to an ad hoc tactical meeting, also when the
  caller unchecked them; fine while holding the role is what counts
  (decided 2026-11-08).
- **First real meetings** in the app: check the mails in real clients
  (several role mails at a meeting's end since elections are announced
  then).
- **Verification** (round of 2026-11-08; fixed: an unfilled Circle Rep
  invited the Circle Leads to ad hoc tactical meetings, a sub-circle
  listed its super-circle's regular tactical meetings; decided: the
  focus of elected roles stays unchangeable, a role's meetings include
  its circle's governance meetings, ad hoc meetings' outputs go to their
  attendees only, a circle's history shows today's roles and the moves
  of those which left; its unproven risks fixed too). Enough rounds
  for the switchover: more would still find bugs, but few that matter
  (decided 2026-11-08); a round when features combine in new ways.
- **Next deploy**: not while a governance meeting which recorded
  elections runs: elections before migration `meetings.0006` lack the
  data to undo them, a correction or the meeting's end would end the
  wrong assignment or announce wrongly. Remove this item afterwards.
- **Published interpretations** (4.2.1): the Secretary's rulings, binding
  for the circle and its sub-circles, shown on the circle page. Postponed,
  we never had the case.
- **Django Tasks** for jobs which belong to a moment, not a schedule:
  ending a meeting when its inactivity runs out (instead of the hourly
  `end_inactive_meetings`), sending mails outside the request.
- **Modals** for more forms where they help.
