# Finding your way

You sign in with your Google account, provided you're recorded as an
active person. Everybody signed in sees everything except others' drafts.

## Navigation

- **Organization**: the anchor circle, from which everything can be
  reached.
- **Circles**: the circle browser shows the circles inside each other. A
  click zooms into a circle, a second one opens its page; the background
  or Escape zooms out again. "My roles" highlights your roles. Below is
  the same structure as a list.
- **Your name** (top right) opens a menu: your page, "Call a tactical
  meeting", **People**
  (everybody with their roles), **Mail addresses**, Help, API and
  signing out. On wide screens **People** is also in the navigation.
- **Proposals**: all proposals, filtered by status, circle (with
  its sub-circles) and the role they change.
- **History**: what changed when; for a circle with its roles ("With
  sub-circles" also what's inside them) or for a role, on request with
  the assignments and with links, notes, metrics and checklists. The pages of
  circles and roles link theirs.
- **Search** finds people (by name, short name and mail address, with their circles),
  roles, accountabilities, domains, policies and links (by title and
  description) containing all the words entered. A link's description
  may list keywords, e.g. for a section of the handbook.

**Mail addresses** lists the addresses of everybody holding a role, of
all Circle Leads, Facilitators, Secretaries and Circle Reps (for
unfilled Facilitators and Secretaries who stands in: the Secretary or
Facilitator, else the Circle Leads) and of each circle's members, to
copy into a mail ("Copy") or to write to them ("New mail"). A circle's
menu "…" links its members.

## Keyboard shortcuts

| Shortcut | |
| --- | --- |
| <kbd>Alt-H</kbd> | Start page: your page |
| <kbd>Alt-O</kbd> | Organization |
| <kbd>Alt-Q</kbd> | Into the search field |

On the Mac <kbd>Ctrl</kbd> instead of <kbd>Alt</kbd>. Hovering over a
link with the mouse shows its shortcut.

## Circles, roles and people

A **circle** shows its purpose, strategy, domains, accountabilities, its
policies, its core roles and meetings, open proposals, checklists and
metrics, links, notes, the history and its roles with their Role Leads (who
fills a role, constitution 1.1; a circle's Role Leads are the Circle
Leads inside it, 1.4). Elected roles whose term ends within 14 days or
which nobody holds are marked "election due", here and on the person
pages of who holds them.
"Members" in the menu "…" shows who fills which of the circle's roles,
a column per member (a hollow dot where the Circle Leads hold a role
nobody holds), then, on the right in gray under "Others", everybody who isn't a
member.
The Circle Leads assign, also people outside the circle, edit the focus
and remove right in the table: hovering over or tapping a cell shows the
buttons.

A **role** shows its purpose, domains, accountabilities, its policies,
who holds it (with focus and term, the Circle Leads assign and remove
here), checklists, metrics, links and notes. Anybody drags the domains and
accountabilities into another order by their handles, which isn't a
change of governance. A domain with policies links to
them ("2 policies"), which opens them; the policies card is there only
when the role has policies of its own. "Domains and policies affecting
this role" in the menu "…" shows what applies to it from outside: the
domains and policies of its circles and the domains of their roles, from
the outermost circle down. Its meetings, those of its circle and those it was invited to (see [Meetings](meetings.md)), are in the menu "…".
Unfilled roles are held by the Circle Leads, except the Circle Rep; an
unfilled Circle Lead by those of the circle above.

**Your page**, the start page, shows your roles, your drafts and tensions, proposals
waiting for your response, your meetings and your settings: name, short
name (in the menu at the top), language (German or English) and mails.
"Settings" in the menu with your name changes them in one form; the
mail address is only shown, you sign in with it.

Running meetings you attend are shown at the top of every page.

## Looking back

Every role and circle has a history: the proposals that changed it, with
the tension and a comparison, and what changed without a proposal (e.g.
in GlassFrog; a role's policies for its domains as "Changed directly",
and by whom). The role's page shows the latest of it and its former
names. "Show as of" shows the structure on an
earlier day, back to 2018.

## Texts

Texts are simple Markdown (`**bold**`, lists with `-`, links). With `@`
you mention a role: the field suggests names, the link always shows the
role's current name.

Short forms (strategy, metrics, checklist items, links, notes, policies of a
domain, settings, assigning, a Role Lead's focus and removing them, the
tension of a draft) open above the page. Escape closes them; once something has
been entered, only when pressed twice.

## Mails

You get mails about the circles you're a member of, that is, where you
hold a role (also as Circle Lead or Circle Rep of a sub-circle):
published and adopted proposals, changed policies of a domain and the
outputs of meetings. You also hear about roles you get or lose and changes of your focus, and as
Secretary about people joining or leaving your circle. As proposer you
hear about questions and requests for a meeting, as Secretary about the
latter, and your questions get their answers by mail. In your settings you
can choose mails about everything in all circles. [Mails](mails.md)
lists them all.

## API

For scripts and other tools: under "API" (in the menu of your name) you create a token (read only,
or read and write, valid until 30 days after its last use). The API reads the structure and
proposals, creates drafts and manages the links of roles and circles; its documentation is at `/api/docs`.

The command line tool `gov` uses the API and gets its token by itself
(`gov login`, confirmed in the browser). It shows circles, roles and
proposals, searches, prepares drafts and manages links (`gov links`); how to install it is on the
"API" page.
