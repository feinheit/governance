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
- **People**: everybody with their roles.
- **Proposals**: all proposals, filtered by status.
- **History**: what changed when, on request with the assignments.
- **Search** finds roles, accountabilities, domains and policies
  containing all the words entered.

## Keyboard shortcuts

| Shortcut | |
| --- | --- |
| <kbd>Alt-H</kbd> | Start page: your page |
| <kbd>Alt-O</kbd> | Organization |
| <kbd>Alt-Q</kbd> | Into the search field |

On the Mac <kbd>Ctrl</kbd> instead of <kbd>Alt</kbd>. Hovering over a
link with the mouse shows its shortcut.

## Circles, roles and people

A **circle** shows its purpose, strategy, accountabilities, domains, its
policies and those of the circles above it, its roles with their holders,
checklists and metrics, links, open proposals, meetings and due
elections.

A **role** shows its purpose, accountabilities, domains, who holds it
(with focus and term), its policies and those of its circles, which
apply to it too, checklists, metrics and links.
Unfilled roles are held by the Circle Leads, except the Circle Rep; an
unfilled Circle Lead by those of the circle above.

**Your page**, the start page, shows your roles, your drafts and tensions, proposals
waiting for your response, your meetings and your settings: mails and
language (German or English).

Running meetings you attend are shown at the top of every page.

## Looking back

Every role and circle has a history: the proposals that changed it, with
the tension and a comparison. "Show as of" shows the structure on an
earlier day, back to 2018.

## Texts

Texts are simple Markdown (`**bold**`, lists with `-`, links). With `@`
you mention a role: the field suggests names, the link always shows the
role's current name.

## Mails

You get mails about the circles you're a member of, that is, where you
hold a role (also as Circle Lead or Circle Rep of a sub-circle):
published and adopted proposals, changed policies of a domain and the
outputs of meetings. You also hear about roles you get or lose, and as
Secretary about people joining or leaving your circle. On your page you
can choose to be informed about everything in all circles.

## API

For scripts and other tools: under "API" you create a token (read only,
or read and write, valid for 90 days). The API reads the structure and
proposals and creates drafts; its documentation is at `/api/docs`.

The command line tool `gov` uses the API and gets its token by itself
(`gov login`, confirmed in the browser). It shows circles, roles and
proposals, searches, and prepares drafts; how to install it is on the
"API" page.
