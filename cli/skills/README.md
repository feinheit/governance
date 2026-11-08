# Claude Code skills for Governance

[Claude Code](https://claude.com/claude-code) skills which do governance
tasks through the `gov` CLI. They prepare, people decide: the skills only
create drafts, which are private until the user publishes them, and stick
to what the user says instead of guessing.

They need `gov`, logged in with `gov login URL --write`. If `gov` only has
read access, the skills ask the user to log in again instead of working
around it.

Link them into your personal skills to use them in any directory (from the
repository root, again when skills are added):

    for skill in "$PWD"/cli/skills/governance-*/; do ln -sfn "${skill%/}" ~/.claude/skills/; done

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
