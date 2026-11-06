---
name: governance-proposal
description: Turn a tension into a governance proposal (a draft) with the `gov` CLI. Use when the user wants to propose a governance change in Governance (the Holacracy app replacing GlassFrog), e.g. add, change, move or remove a role, an accountability, a domain or a policy, or wants help phrasing a tension as a proposal.
---

# Preparing a governance proposal from a tension

The `gov` CLI talks to Governance (see `gov --help`). Proposals created
through it are **drafts**: only the proposer sees them until they publish
them or bring them into a governance meeting. The skill prepares the draft,
the user decides what happens with it.

If `gov` isn't installed or configured, tell the user to run
`uv tool install "git+https://github.com/feinheit/governance#subdirectory=cli"`
and `gov login URL --write`, which authorizes `gov` in the browser. Creating
drafts needs `--write`; if `gov` answers that the token only allows reading,
ask the user to log in with `--write` instead of working around it.

## 1. Understand the tension

A proposal addresses a tension of one of the user's roles in a circle. Find
out, in the user's words:

- **the role** the tension comes from, and its circle: `gov me` lists the
  user's roles with their IDs, grouped by circle. If it isn't obvious, ask.
- **the tension**: the gap between what is and what could be, from the
  role's point of view.
- **an example**: a past or current situation where the tension showed. Ask
  for one if the user didn't give it; don't invent it.

The proposal belongs to the circle of that role (or, to add roles inside one
of the user's roles, to that role itself, which then becomes a circle).

## 2. Read the current governance

Get the exact current state, with IDs and texts, before writing anything:

    gov circles show <circle_id> --json
    gov roles show <role_id> --json
    gov policies --circle <circle_id>
    gov domains --circle <circle_id>
    gov search <terms>

Look for what already covers the tension: an existing role, accountability,
domain or policy may only need a small change, or the tension may belong to
another circle. Propose the smallest change which resolves the tension, and
mention overlaps you found. Follow the style of the existing texts in the
circle (language, wording; accountabilities usually describe an ongoing
activity, domains a thing or an area the role controls).

## 3. Write the instructions

Instructions use GlassFrog's format, as a YAML list. Paths refer to roles
and policies of the proposal's circle by their ID; objects the proposal adds
get keys `n1`, `n2`, … (one counter for all of them) and must be added
before they're used:

```yaml
# A new role with a purpose, an accountability and a domain
- op: add
  path: /roles/n1
- op: add
  path: /roles/n1/name
  value: Baker
- op: add
  path: /roles/n1/aim            # aim is the purpose
  value: Bread for everyone
- op: add
  path: /roles/n1/accountabilities/n2
  value: Baking bread every morning
- op: add
  path: /roles/n1/domains/n3
  value: The oven

# Changing an existing role: always with the current value
- op: replace
  path: /roles/34/name
  original_value: Cook
  value: Chef
- op: replace
  path: /roles/34/accountabilities/56
  original_value: Cooking soup
  value: Cooking soup and stew
- op: remove
  path: /roles/34/domains/78
  original_value: The fridge

# A new policy of the circle, changing and removing policies
- op: add
  path: /policies/n4
- op: add
  path: /policies/n4/title
  value: Cleaning up
- op: add
  path: /policies/n4/body
  value: Whoever cooks cleans up.
- op: replace
  path: /policies/90/body
  original_value: <the current text>
  value: <the new text>
- op: remove
  path: /policies/91

# Removing a role, turning a role into a circle and back
- op: remove
  path: /roles/35
- op: add
  path: /roles/36/supporting_circle
- op: remove
  path: /roles/37/supporting_circle

# Moving a role (or policy) into a sub-circle, and out of one
- op: move
  from: /roles/38
  path: /roles/39/supporting_circle/roles/38
- op: move
  from: /circles/39/roles/40
  path: /roles/40
```

Rules the server enforces (it reports them as problems):

- `original_value` must be the current text exactly; copy it from
  `gov roles show --json`. It lets the server detect changes since drafting.
- The core roles (Circle Lead, Facilitator, Secretary, Circle Rep) keep
  their names and purposes. Accountabilities and domains can be added to
  them, but not to the Circle Lead.
- A new role or policy needs a name or title.
- Roles and policies outside the proposal's circle can't be changed.

## 4. Create the draft

Write the tension with the sections of the web form, in the user's language
(German headings for a German organization):

```markdown
## Die Spannung aus Sicht der Rolle

…

## Ein Beispiel einer vergangenen oder aktuellen Situation

…

## Wie der Vorschlag die Spannung im Beispiel adressiert

…
```

Then create the draft, the scratch files in a temporary directory:

    gov proposals create --circle <circle_id> --role <role_id> \
      --tension - --instructions <scratchpad>/instructions.yaml < <scratchpad>/tension.md

To break down one of the user's roles into roles (1.3.1), the role is the
circle too (`--circle <role_id> --role <role_id>`): adopting the first
role makes it a circle with its holders as Circle Leads.

`gov` shows the readable changes and the **problems** which would prevent
adopting it. Fix them with

    gov proposals update <id> --instructions <scratchpad>/instructions.yaml
    gov proposals update <id> --tension - < <scratchpad>/tension.md

until there are none. A draft without instructions stays a tension, which is
fine if the user only wants to note it.

## 5. Let the user decide

Show the user the draft's URL, the tension and the changes, the overlaps you
found and your open questions. Then ask what to do:

- **Publish it asynchronously** (`gov proposals publish <id>`): the circle's
  members get a mail and respond until the deadline; without requests for a
  meeting it's adopted. Only do this after the user explicitly said so.
- **Bring it into the next governance meeting**: the user adds it to the
  agenda in the app.
- **Leave it as a draft** to look at it in the app first.

Never publish on your own, and don't add changes the tension doesn't need.
`gov` only changes the user's own drafts.
