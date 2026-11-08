---
name: governance-review
description: Review the governance of a circle or a role in Governance (the Holacracy app replacing GlassFrog) with the `gov` CLI. Checks whether purposes, accountabilities, domains and policies are well formulated, unambiguous and valid under the Holacracy constitution, and points out policies which belong in a handbook or in employment rules rather than in governance. Use when the user asks to review, audit, check or clean up a circle's or role's governance.
---

# Reviewing the governance of a circle or a role

The review reads, it changes nothing. It ends with findings and concrete
rewordings; the user decides which ones become proposals (with the
`governance-proposal` skill, one tension at a time).

If `gov` isn't installed or configured, tell the user to run
`uv tool install "git+https://github.com/feinheit/governance#subdirectory=cli"`
and `gov login URL`. Reading is enough for the review. `gov constitution`
and `gov roles context` need `gov` 0.10.0 or later: `uv tool upgrade governance-cli`.

## 1. Read the governance

Find the circle or role (`gov circles` shows the tree with IDs,
`gov search <terms>` finds roles and policies by their texts), then read
everything with its exact texts:

    gov circles show <circle_id> --json     # the circle, its roles and policies
    gov roles show <role_id> --json         # a role, its Role Leads
    gov roles context <role_id> --json      # what affects it from outside
    gov policies --circle <circle_id> --json  # also the roles' domain policies
    gov domains --circle <circle_id>
    gov export --json                       # the whole organization as a tree

For a circle, review the circle's own purpose, accountabilities and
domains, each of its roles and all of its policies. For a role, review the
role and the policies for its domains, and read its circle for context:
every text is interpreted in the light of the circle's purpose (4.2), and
overlaps with sibling roles only show there. Review sub-circles only when
the user asks for them.

**The context** (`gov roles context`, for circles too): per circle
containing the role or circle, from the anchor circle down, the circles'
domains and policies and the domains of their other roles with their
policies. Policies apply in sub-circles too unless they say otherwise
(5.2.1), and a domain of another role (e.g. the anchor circle's IT
holding the laptops) limits everybody else (4.1.2). For a sub-circle
this is essential: read it before judging, and report

- policies of the circle repeating, contradicting or loosening those
  of a super-circle (a sub-circle can't grant authority its
  super-circle constrains; it may only override a super-circle's
  change of a constitutional default, unless that policy forbids it),
- accountabilities and domains which overlap with what a super-circle
  or one of its roles holds, or which need another role's domain to be
  enacted without saying so,
- gaps the context makes visible, e.g. a super-circle's policy that
  refers to a role or process the circle lacks.

Texts mention roles as `@[Name](role:ID)`; quote them by name.

Read the constitution the app follows (Holacracy 5.0) before judging,
in the language of the governance, and cite its sections in the
findings:

    gov constitution --language de > <scratchpad>/constitution.md

Above all 1.1 (purpose, domains, accountabilities, policies), 1.3 and
1.4 (circles, Circle Leads), 2.4 (relational agreements), 4.1
(constraints on authority, domains, spending) and 5.2 (what governance
may decide, 5.2.1 what a policy may be).

The core roles (Circle Lead, Facilitator, Secretary, Circle Rep) and
their constitutional texts come from the app, which allows no added
accountabilities or domains on them: don't review those. Do report
circle accountabilities or policies which redo their job, e.g. a
policy restating how governance meetings work.

## 2. Check each element

The constitution's definitions are the yardstick. Quote the
element, say what's wrong and propose a better wording in the language
of the governance. Don't report what's fine, except as a short summary.

**Purpose**: a capacity, potential or goal the role pursues or expresses,
not a list of tasks and not the accountabilities again. Vague purposes
("Support the team") give no direction for prioritizing.

**Accountabilities** are ongoing activities the role enacts, which others
may expect of it. Check that each one:

- describes an **activity the role does**, not an outcome it has to
  guarantee. "Ensuring invoices are paid on time", "Sicherstellen, dass
  die Website aktuell ist" or "The CRM is up to date" make the role
  answerable for a state of the world it doesn't fully control, and nobody
  can tell when it's done enough. Name the activity instead: "Sending
  invoices and reminding customers of overdue ones", "Inhalte der Website
  aktualisieren". If an "ensure" hides a monitoring job, say that:
  "Monitoring X and raising tensions about Y".
- is **ongoing**, not a one-off project ("Setting up the new server" is
  a project of some role, not an accountability).
- is **specific enough to expect and to refuse**: someone reading it can
  tell whether a request falls within it. "Supporting colleagues",
  "Everything about marketing" fail this.
- starts with the activity (in English an -ing verb, in German usually a
  verb or a noun of an action), and is one activity, not several joined
  with "and" where they could stand alone.
- doesn't duplicate an accountability of another role in the circle, or
  of a core role, or the duties every partner has anyway (processing
  tensions, transparency, 1.2, 2.1).

**Domains** are things the role exclusively controls: assets, processes,
systems, documents, channels. Check that each one:

- is a **thing**, not an activity ("Managing the newsletter" is an
  accountability, "The newsletter's mailing list" a domain).
- has **clear boundaries**: "Marketing" or "IT" doesn't say what others
  may touch without asking (4.1.2); "The website's content management
  system" does.
- isn't held by two roles at once, and is backed by an accountability
  when the role is expected to do something with it.

**Policies** may only (5.2.1) constrain the authority of the circle's
roles, grant authority the circle or the Circle Lead holds to roles, grant
or constrain access to one of the circle's domains, or change a default
rule of the constitution where it allows that. Check that each one:

- **addresses roles, not people**. A policy limits what a role may do
  ("Roles spending more than CHF 1000 announce it in #finance first"),
  it can't oblige humans as persons. Rules about how people behave as
  employees (working hours, holidays and absences, sick leave, expenses,
  training budgets, side jobs, conduct, personal use of equipment,
  language at work) aren't valid governance, however sensible they are.
  They belong in the handbook (as information), in the employment
  contract or staff regulations (as instructions of the employer under
  employment law, e.g. in Switzerland the Code of Obligations), or in
  relational agreements between partners (2.4), which bind only those
  who agree. Say where such a policy would fit better, and what the
  governance could keep: usually a role with an accountability or a
  domain for it ("Maintaining the staff regulations", domain "Approving
  holidays"), so that it's clear who changes those rules and who
  decides cases.
- is **unambiguous**: who (which roles) may or may not do what, when.
  Look for "should", "if possible", "in general", "appropriate",
  "regularly", "important" without a measure, undefined terms, and
  exceptions without a role deciding them. Say what two readers could
  disagree about.
- **has a rule in it**: descriptions, explanations, background, links
  and how-tos are documentation; keep the rule, move the rest to the
  handbook or a link.
- doesn't repeat the constitution, contradict another policy, or
  assign work: "Role X does Y every month" is an accountability of X
  (or a checklist item), not a policy.
- if it's a role's policy, concerns that role's domain.

Also look at the whole: activities nobody holds, roles without
accountabilities or Role Leads, roles whose name promises more than their
accountabilities, and anything which looks out of date. Say that it's a
guess where you only suspect it.

## 3. Report

In the user's language, short:

1. A summary: the overall state and the few changes which matter most.
2. The findings, grouped by role and the circle's policies, each with
   the quoted text, the problem in one sentence and the proposed text.
   Mark policies which don't belong in governance, with where they
   would fit better.
3. Questions where only the people in the roles know the answer (what an
   accountability really means, whether a domain is used).

Be concrete and constructive, and don't rewrite what works: the
circle's members wrote these texts and will have to agree to the
changes. Employment law (Swiss for now) and the organization's handbook
are context, not a checklist: point out where something looks like it
needs a legal basis or a contract, don't give legal advice.

## 4. Next steps

Offer to prepare proposals for the findings the user picks, with the
`governance-proposal` skill: one draft per tension, from one of the
user's roles in the circle (`gov me`), with the review's finding as the
example. Policies moving out of governance need their new home first
(the handbook, the regulations); the proposal then removes the policy and
may add the role or domain which keeps it maintained. Create nothing
without the user asking for it.
