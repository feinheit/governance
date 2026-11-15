# Claude Code skills for Governance

[Claude Code](https://claude.com/claude-code) skills which do governance
tasks through the `gov` CLI. They prepare, people decide: the skills only
create drafts, which are private until the user publishes them, or tasks
the user confirmed, and stick to what the user says instead of guessing.

They need `gov`, logged in with `gov login URL --write`. If `gov` only has
read access, the skills ask the user to log in again instead of working
around it.

They come with `gov`, link them into your personal Claude Code skills:

    gov skills install

The links point to where `gov` is installed (the checkout for editable
installs), upgrading `gov` updates the skills. Run it again when `gov`
brings new skills (`gov skills list` shows them), `--project` links them
into the project in the current directory instead (`.claude/skills`),
`gov skills uninstall` removes the links.

## governance-proposal

Turns a tension into a draft proposal. It asks for the role the tension
comes from (`gov me`), the tension and an example, reads the circle's
current roles, accountabilities, domains and policies, looks for what
already covers the tension and writes the smallest change in GlassFrog's
instruction format. It creates the draft with `gov proposals create`, fixes
the problems the server reports, and shows the user the result.

Publishing (the circle's members get a mail) only happens when the user
explicitly asks for it; otherwise the draft stays private or goes into the
next governance meeting.

## governance-review

Reviews the governance of a circle or a role against the Holacracy
Constitution (`gov constitution`): purposes, accountabilities which are
activities rather than outcomes to ensure, domains with clear
boundaries, unambiguous policies which constrain roles, not people.
Policies which are really employment rules or documentation get a
suggestion where they would fit better (the handbook, the staff
regulations, relational agreements). It only reads; the findings the
user picks become drafts with `governance-proposal`.

## governance-tactical

Follows up on a tactical meeting (`gov meetings show`): proposes a task in
the circle's task management tool for each outcome without a link, with
the outcome's words as its title, all Role Leads of the mentioned role as
assignees (matched by email, one task for all of them or one each,
asking when the outcome doesn't say; they get back to who asked if they disagree; without a mention the item's owner, marked
as a guess) and a link back to the meeting, and checks the tasks already
linked (missing, unassigned, a different title). It creates or changes
tasks only after the user confirmed the list, through whatever reaches
the task management tool in the session (its skill, connector or command
line tool); without one it writes a Markdown to-do list. It names no
tool: the circle's links say where the projects are.
