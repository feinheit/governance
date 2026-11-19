---
name: governance-tactical
description: Turn the outcomes of a tactical meeting in Governance (the Holacracy app replacing GlassFrog) into tasks in the circle's task management tool, and check the tasks already linked, with the `gov` CLI. Use when the user (usually the meeting's Secretary) wants to follow up on a tactical meeting, create the next actions and projects from its outcomes, or asks whether a meeting's tasks are all captured.
---

# Following up on a tactical meeting

Governance records what a tactical meeting decided: per agenda item an
outcome (often a project phrased as its result, or a next action, naming
the role taking it on with `@`) and optionally a link, usually to the task
created for it. The tasks themselves live in the circle's task management
tool, not in Governance. This skill brings both together: it creates the
missing tasks and checks the linked ones. It proposes, the user decides:
nothing is created or changed in the task management tool before the user
confirmed the list.

If `gov` isn't installed or configured, tell the user to run
`uv tool install "git+https://github.com/feinheit/governance#subdirectory=cli"`
and `gov login URL`. Reading is enough, the skill changes nothing in
Governance. `gov meetings` needs `gov` 0.26.0 or later:
`uv tool upgrade governance-cli`.

The tasks are created with whatever reaches the task management tool in
this session: its skill, its connector or its command line tool. Find out
which tool it is from the URLs of the circle's links and of the tasks
already linked. If nothing in this session reaches it, say so and write
the tasks as a Markdown to-do list the user can paste instead; don't try
to work around it (e.g. with scraped pages or guessed APIs).

## 1. Find the meeting

The user gives the meeting (its URL ends with `/meetings/<id>/`) or the
circle; otherwise ask. A circle's newest tactical meetings, with the number
of items having an outcome or a link:

    gov meetings --circle <circle_id> --kind tactical

Take the newest ended one unless the user means another, then read it:

    gov meetings show <meeting_id> --json

It has the agenda `items` (each with `label`, `owner`, `outcome` with
mentions as `@[Name](role:ID)`, `outcome_plain` with the roles' current
names, `roles`: the mentioned roles with their `role_leads` and their
email addresses, and `link`), the `links` of the circle (an ad hoc
meeting's of the invited roles' circles: where their projects are), `minutes` and `url`. Leave `attendees`
alone: who was invited needn't attend, and the list isn't kept
reliably, so it says nothing about who takes on a task. A
running meeting works too, with the items so far; say that it isn't over.

## 2. Sort the items

- **No outcome and no link**: nothing to do; many items end with
  information or a short discussion.
- **An outcome, no link**: a task to create (step 3).
- **A link to a task**: a task to check (step 4).
- **An outcome about governance** (a tension for a governance meeting, a
  proposal): its owner writes it down in Governance, the skill doesn't
  draft the proposal. A to-do reminding them is a task like the others
  (step 3), e.g. "Bring the tension about … to the governance meeting",
  assigned to whoever the outcome names, else to the item's owner.

Links which don't point to a task (a document, a page) are references;
keep them in the task's description instead of checking them.

## 3. Propose the tasks to create

**Where.** The meeting's `links` say where the projects of the circle and
the invited roles are, their titles and descriptions which list is which.
Tasks already linked in this meeting show where the secretary put the
others. Per task, in this order:

1. A link whose name (more or less) matches the outcome's subject: use
   that list.
2. Otherwise the circle's general list for everyone, if there is one.
3. Otherwise ask; don't create new lists, and never guess a project or
   list. Ask too when several links match equally well.

When the link points to a card table (a Kanban board) instead of a to-do
list, create cards there instead of to-dos, in its first column for new
cards unless the user says otherwise.

**Per task:**

- **Title**: the outcome's own words, in the meeting's language. A project
  stays phrased as its result ("The offer is submitted"), a next action as
  what is done. Don't embellish, translate or merge outcomes; one item with
  several outcomes may become several tasks.
- **Assignees**: the Role Leads of the mentioned role (`roles[].role_leads`),
  matched to people in the task management tool by their email address,
  all of them when several fill it, unless the outcome names one: they
  take the task on because they hold the role, not because they agreed
  in the meeting. Several people: one task assigned to all of them when
  it's done once for the role (whoever gets to it first), one task per
  person when each of them has to do it (e.g. everybody updates their
  own entries). If the outcome doesn't make it clear, ask, for that item. Whoever disagrees, or doesn't think the task can be
  expected of the role, gets back to the one who asked; that's not the
  skill's to settle. An unfilled role: leave it unassigned and say so.
  **Without a mention**, the item's owner (who brought the tension) is
  only a guess: propose it, marked as such. Never assign someone who
  doesn't show up in the data.
- **Description**: the agenda item's label, the outcome, who asked for it
  (the item's `owner`, to get back to) and a link to the meeting (`url`),
  so that the task says where it came from.
- **Due date**: only when the outcome names one.

Show the user the list before creating anything, e.g. as a table: item,
title, where, assignee (guesses marked), plus the items left out and why.
Create the tasks the user confirms, with the changes they ask for, and
list the created tasks with their URLs at the end.

## 4. Check the linked tasks

Read each linked task in the task management tool and report what doesn't
fit, with a proposed fix:

- it doesn't exist (anymore), or the link points to something else;
- it is completed already (fine, just say so) or archived;
- it has no assignee, or someone who doesn't fill the mentioned role;
- its title says something else than the outcome;
- it doesn't link back to the meeting.

Apply only the fixes the user confirms. Linked tasks that fit need one
line, not a report.

## 5. Afterwards

`gov` only reads meetings, the links of the created tasks don't go back
into Governance by themselves. While the meeting still runs, the
Secretary can paste them into the items' "Link" fields: list them per
item for that. After the meeting ended its items can't be changed; the
next tactical meeting's progress updates show the circle's links, where
the tasks are.
