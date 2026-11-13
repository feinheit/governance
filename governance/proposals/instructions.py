"""Applying a proposal's instructions, see section 3 of SPEC.md

Instructions use GlassFrog's format (``add``, ``replace``, ``remove``,
``test`` with ``original_value``). The app's proposals refer to the app's
IDs; objects added by a proposal get keys like ``n1`` until the proposal is
adopted, then their IDs.

``adopt()`` applies everything in one transaction or nothing: conflicts
(the target changed since the proposal was drafted) and violations of the
constitution's rules raise ``ProposalError`` with all problems found.
``problems()`` runs the same code and rolls back, for drafts.
"""

import re
from contextlib import nullcontext
from functools import partial

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from governance.history.update import update_changes
from governance.locking import lock_structure
from governance.notifications import mails
from governance.notifications.role_leads import announce
from governance.proposals.models import Proposal
from governance.roles.assignments import (
    new_reps_leading,
    reps_leading_their_circle,
    sync_circle_role_leads,
)
from governance.roles.constitution import CORE_ROLES, LEAD
from governance.roles.models import Accountability, Assignment, Domain, Policy, Role
from governance.roles.permissions import members


KEY = r"(\d+|n\d+)"
# Left from merging texts changed in the meantime (``drafting.MergeMixin``)
MARKERS = re.compile(r"^(<{7}|>{7})( .*)?$|^={7}$", re.MULTILINE)
NEW_KEY = re.compile(r"n(\d+)")
ROLE_FIELDS = {"name": "name", "aim": "purpose"}
POLICY_FIELDS = {"title": "title", "body": "body"}
TEXTS = {"accountabilities": Accountability, "domains": Domain}
CORE = list(CORE_ROLES)


class ProposalError(Exception):
    def __init__(self, problems):
        super().__init__("; ".join(problems))
        self.problems = problems


class Rollback(Exception):
    pass


def new_key(instructions):
    """The next free key for an object added by the proposal"""
    numbers = [
        int(number)
        for instruction in instructions
        for number in re.findall(r"/n(\d+)", instruction["path"])
    ]
    return f"n{max(numbers, default=0) + 1}"


def subject_of(path):
    """``roles/123`` or ``policies/n1`` for a path

    Moving into a sub-circle (``/roles/SUB/supporting_circle/roles/123``)
    belongs to the moved role or policy.
    """
    match = re.fullmatch(
        rf"/roles/{KEY}/supporting_circle/(roles|policies)/{KEY}", path
    )
    if match:
        return f"{match[2]}/{match[3]}"
    match = re.match(rf"/(roles|policies)/{KEY}", path)
    return f"{match[1]}/{match[2]}" if match else None


class Applier:
    def __init__(self, proposal):
        self.proposal = proposal
        # A copy: dry runs (problems(), consequences()) change it in memory
        # and roll back only the database
        self.circle = Role.objects.get(pk=proposal.circle_id)
        self.day = timezone.localdate()
        self.created = {}  # "roles/n1" → object
        self.problems = []
        self.roles = set()
        self.policies = set()
        self.converted = []  # Roles turned into circles
        # Circles which lost roles: without roles of their own afterwards
        # they turn back into roles (finish())
        self.shrunk = set()
        self.reverted = []
        # Those with a meeting of their own running turn back when it ends
        # (revert_after_meeting()), after its closing round
        self.deferred = []
        # Roles and circles removed, also those inside removed circles
        self.removed = []
        self.made_circles = []  # Automatically, by adding roles inside
        self.ended_users = set()
        # Circle Reps leading their circle afterwards resign (5.1.1)
        self.ended_reps = []

    def problem(self, message, **kwargs):
        # Once, even if several instructions refer to the missing role
        if (problem := message % kwargs) not in self.problems:
            self.problems.append(problem)

    def get(self, kind, key, *, allow_archived=False, circle=None, deep=False):
        """The role or policy of a path, checked against the circle (``deep``:
        also a circle in any sub-circle thereof, 5.2)"""
        circle = circle or self.circle
        if NEW_KEY.fullmatch(key):
            if f"{kind}/{key}" not in self.created:
                self.problem(
                    _("The proposal refers to %(key)s before adding it."), key=key
                )
            # None if adding it was refused, which is the problem
            return self.created.get(f"{kind}/{key}")
        model = Role if kind == "roles" else Policy
        obj = model.objects.filter(pk=key).first()
        if obj is None or (obj.archived_on and not allow_archived):
            self.problem(
                _("%(object)s doesn't exist anymore."),
                object=self.proposal.names.get(f"{kind}/{key}") or f"{kind}/{key}",
            )
            return None
        if kind == "policies" and not obj.role.is_circle:
            # Removing the domain archives them (apply_to_text())
            self.problem(
                _(
                    "%(policy)s is a policy of %(role)s for its domains, the role changes it."
                ),
                policy=obj,
                role=obj.role,
            )
            return None
        if kind == "roles":
            # The anchor circle governs its own purpose and accountabilities
            # (constitution 1.3.3), other roles are governed by their circle
            owner = obj.pk if obj.circle_id is None else obj.circle_id
        else:
            owner = obj.role.governing_circle_id
        if owner != circle.pk and not (
            deep
            and kind == "roles"
            and obj.is_circle
            and circle.pk in {c.pk for c in obj.ancestors()}
        ):
            self.problem(
                _("%(object)s isn't governed by %(circle)s."),
                object=obj,
                circle=circle,
            )
            return None
        (self.roles if kind == "roles" else self.policies).add(obj)
        return obj

    def check_value(self, label, value):
        if isinstance(value, str) and MARKERS.search(value):
            self.problem(_("%(label)s still contains conflict markers."), label=label)
            return False
        return True

    def check_original(self, label, current, instruction):
        original = instruction.get("original_value")
        if original is not None and (current or "") != (original or ""):
            self.problem(
                _("%(label)s has been changed since the proposal was drafted."),
                label=label,
            )
            return False
        return True

    def apply(self, instructions):
        if self.circle.archived_on:
            # Removed since: its proposals are withdrawn with it
            self.problem(_("%(object)s doesn't exist anymore."), object=self.circle)
            raise ProposalError(self.problems)
        self.reps_before = reps_leading_their_circle()
        for instruction in instructions:
            self.apply_one(instruction)
        for kind, obj in self.created.items():
            if (
                obj is not None
                and kind.startswith(("roles/", "policies/"))
                and not str(obj).strip()
            ):
                self.problem(_("A new role or policy needs a name."))
        if self.problems:
            raise ProposalError(self.problems)

    def apply_one(self, instruction):
        """Applies one instruction, according to what its path refers to"""
        op, path = instruction["op"], instruction["path"]
        if op == "move":
            self.move(instruction)
        elif match := re.fullmatch(rf"/(roles|policies)/{KEY}", path):
            self.apply_to_object(instruction, match[1], match[2])
        elif op not in {"add", "replace", "remove"}:
            # Tests check objects only, not fields (they'd set them unseen)
            self.unsupported(path)
        elif match := re.fullmatch(rf"/roles/{KEY}/(name|aim)", path):
            self.apply_to_role_field(instruction, match[1], ROLE_FIELDS[match[2]])
        elif match := re.fullmatch(rf"/policies/{KEY}/(title|body)", path):
            self.apply_to_policy_field(instruction, match[1], POLICY_FIELDS[match[2]])
        elif match := re.fullmatch(
            rf"/roles/{KEY}/(accountabilities|domains)/{KEY}(?:/description)?", path
        ):
            self.apply_to_text(instruction, match[1], match[2], match[3])
        elif (
            match := re.fullmatch(rf"/roles/{KEY}/supporting_circle", path)
        ) and op in {"add", "remove"}:
            self.apply_to_supporting_circle(instruction, match[1])
        else:
            self.unsupported(path)

    def apply_to_object(self, instruction, kind, key):
        """Adds, removes or checks a role or a policy (``/roles/123``)"""
        op = instruction["op"]
        if op == "test":
            self.get(kind, key)
        elif op == "add":
            # Empty until the following instructions set its name or title
            if kind == "roles":
                # Roles inside a role make it a circle (constitution
                # 1.3.1), recorded when adopting
                self.make_circle(self.circle)
                obj = Role.objects.create(circle=self.circle, name="")
                self.roles.add(obj)
            else:
                if not self.circle.is_circle:
                    # Set on its page, without governance (1.3.2)
                    self.problem(
                        _("%(role)s only has policies for its domains."),
                        role=self.circle,
                    )
                    self.created[f"{kind}/{key}"] = None
                    return
                obj = Policy.objects.create(role=self.circle, title="")
                self.policies.add(obj)
            self.created[f"{kind}/{key}"] = obj
        elif op == "remove":
            if (obj := self.get(kind, key)) is not None:
                self.remove(obj)
        else:
            self.unsupported(instruction["path"])

    def apply_to_role_field(self, instruction, key, field):
        """Sets a role's name or purpose (``/roles/123/aim``)"""
        role = self.get("roles", key)
        if role is None:
            return
        if role.core_role:
            self.problem(_("The constitution defines %(role)s."), role=role)
            return
        self.set_field(role, field, instruction)

    def apply_to_policy_field(self, instruction, key, field):
        """Sets a policy's title or body (``/policies/123/body``)"""
        policy = self.get("policies", key)
        if policy is not None:
            self.set_field(policy, field, instruction)

    def set_field(self, obj, field, instruction):
        value = instruction.get("value")
        label = f"{obj}: {field}"
        if (
            field in {"name", "title"}
            and not (value or "").strip()
            # New ones without a name are reported by apply()
            and obj not in self.created.values()
        ):
            self.problem(_("%(label)s can't be empty."), label=label)
            return
        if self.check_value(label, value) and self.check_original(
            label, getattr(obj, field), instruction
        ):
            setattr(obj, field, value or "")
            obj.save(update_fields=[field])

    def apply_to_text(self, instruction, role_key, kind, key):
        """Adds, changes or removes an accountability or a domain of a role
        (``/roles/123/domains/456``)"""
        op, value = instruction["op"], instruction.get("value")
        role = self.get("roles", role_key)
        if role is None:
            return
        if role.core_role:
            # The app leaves the core roles as the constitution defines them,
            # on purpose: additions to the Circle Lead would apply to all
            # sub-circles' Circle Leads (1.4.5), the circle's own core roles
            # (1.3.3, 5.1.1) don't need them (decided 2026-11-07)
            self.problem(
                _(
                    "Core roles get no accountabilities or domains besides the"
                    " constitution's."
                )
            )
            return
        model = TEXTS[kind]
        if not self.check_value(str(role), value):
            return
        if op in {"add", "replace"} and not (value or "").strip():
            self.problem(
                _("Accountabilities and domains of %(role)s can't be empty."),
                role=role,
            )
            return
        if op == "add":
            obj = model.objects.create(
                role=role,
                text=value or "",
                position=role_texts_count(model, role),
            )
            self.created[f"{kind}/{key}"] = obj
            return
        if NEW_KEY.fullmatch(key):
            # Added by the proposal before
            obj = self.created.get(f"{kind}/{key}")
            if obj is not None and obj.role_id != role.pk:
                obj = None
        else:
            obj = model.objects.filter(pk=key, role=role).first()
        if obj is None:
            self.problem(
                _("%(text)s doesn't exist anymore."),
                text=instruction.get("original_value") or instruction["path"],
            )
            return
        if not self.check_original(f"{role}: {obj}", obj.text, instruction):
            return
        if op == "remove":
            if model is Domain:
                # The role's policies regulating it go with it
                policies = obj.policies.active()
                self.policies.update(policies)
                policies.update(archived_on=self.day)
            obj.delete()
            if NEW_KEY.fullmatch(key):
                self.created[f"{kind}/{key}"] = None
        elif op == "replace":
            obj.text = value or ""
            obj.save(update_fields=["text"])
        else:
            self.unsupported(instruction["path"])

    def apply_to_supporting_circle(self, instruction, key):
        """Turns a role into a circle (``add``) or back (``remove``)"""
        role = self.get("roles", key)
        if role is None:
            return
        to_circle = instruction["op"] == "add"
        self.convert(role, to_circle=to_circle)
        if not to_circle and not role.is_circle:
            # Closes like a circle turning back automatically (finish())
            self.reverted.append(role)

    def move(self, instruction):
        """Moves a role or policy into a sub-circle, or out of one"""
        path, source = instruction["path"], instruction.get("from", "")
        if match := re.fullmatch(
            rf"/roles/{KEY}/supporting_circle/(roles|policies)/{KEY}", path
        ):
            # Into a sub-circle or any sub-circle thereof (5.2)
            target = self.get("roles", match[1], deep=True)
            obj = self.get(match[2], match[3])
            kind = match[2]
        elif (match := re.fullmatch(rf"/(roles|policies)/{KEY}", path)) and (
            source_match := re.fullmatch(
                rf"/circles/{KEY}/(roles|policies)/{KEY}", source
            )
        ):
            kind = match[1]
            source_circle = self.get("roles", source_match[1], deep=True)
            if source_circle is None:
                return
            if not source_circle.is_circle:
                self.problem(_("%(role)s isn't a circle."), role=source_circle)
                return
            target = self.circle
            obj = self.get(kind, match[2], circle=source_circle)
        else:
            self.unsupported(path)
            return
        if target is None or obj is None:
            return
        if (
            not target.is_circle
            and kind == "roles"
            and not target.core_role
            and target.circle_id == self.circle.pk
        ):
            # Moving roles into a role makes it a circle
            self.make_circle(target)
        if not target.is_circle:
            self.problem(_("%(role)s isn't a circle."), role=target)
        elif kind == "roles":
            if (
                obj.core_role
                or obj.circle_id is None
                # Not into its own inside
                or obj.pk in {target.pk, *(c.pk for c in target.ancestors())}
            ):
                self.problem(_("%(role)s can't be moved."), role=obj)
                return
            self.shrunk.add(obj.circle)
            obj.circle = target
            obj.save(update_fields=["circle"])
        elif obj.domain_id:
            # Like the policies of roles for their domains, which get()
            # refuses: the policy stays with the role holding the domain
            self.problem(
                _("%(policy)s regulates a domain of %(role)s and stays with it."),
                policy=obj,
                role=obj.role,
            )
        else:
            obj.role = target
            obj.save(update_fields=["role"])

    def unsupported(self, path):
        self.problem(_("The app can't apply %(path)s yet."), path=path)

    def remove(self, obj):
        if isinstance(obj, Policy):
            obj.archived_on = self.day
            obj.save(update_fields=["archived_on"])
            return
        if obj.core_role:
            self.problem(_("The constitution defines %(role)s."), role=obj)
            return
        if obj.circle_id is None:
            self.problem(_("The anchor circle can't be removed."))
            return
        self.shrunk.add(obj.circle)
        self.archive(obj)

    def archive(self, role):
        """Archives the role, and everything a circle still contains: roles
        and policies to keep are moved out first (like in GlassFrog)"""
        for child in role.roles.active():
            self.archive(child)
        for assignment in Assignment.objects.current().filter(role=role):
            self.end_assignment(assignment)
        role.archived_on = self.day
        role.save(update_fields=["archived_on"])
        # Their history lists the proposal
        self.roles.add(role)
        policies = role.policies.active()
        self.policies.update(policies)
        policies.update(archived_on=self.day)
        self.removed.append(role)

    def end_assignment(self, assignment):
        # Those losing roles hear about the proposal, also deeper inside
        self.ended_users.add(assignment.user_id)
        assignment.end(self.day)

    def make_circle(self, role):
        """Turns the role into a circle if needed, once"""
        if not role.is_circle:
            self.convert(role, to_circle=True)
            if role.is_circle:
                self.made_circles.append(role)

    def convert(self, role, *, to_circle):
        if to_circle and role in self.converted:
            # Done before in this proposal; GlassFrog repeats it for new
            # circles after moving roles into them
            return
        if role.core_role or role.is_circle == to_circle or role.circle_id is None:
            self.problem(
                _("%(role)s can't be turned into a circle or back."), role=role
            )
            return
        if to_circle:
            role.is_circle = True
            role.save(update_fields=["is_circle"])
            role.create_core_roles()
            self.converted.append(role)
            # The role's Role Leads lead the new circle
            lead = role.roles.active().get(core_role=LEAD)
            for assignment in Assignment.objects.current().filter(role=role):
                Assignment.objects.create(
                    role=lead, user=assignment.user, starts_on=self.day
                )
            return
        if role.roles.active().exclude(core_role__in=CORE).exists():
            self.problem(
                _("%(circle)s still has roles, they have to go first."), circle=role
            )
            return
        # The role stays with its Circle Leads, not with its Circle Rep
        leads = set(
            Assignment.objects
            .current()
            .of_core_role(LEAD, role)
            .values_list("user", flat=True)
        )
        for assignment in Assignment.objects.current().filter(role=role):
            if assignment.user_id not in leads:
                self.end_assignment(assignment)
        for core_role in role.roles.active():
            for assignment in Assignment.objects.current().filter(role=core_role):
                self.end_assignment(assignment)
            core_role.archived_on = self.day
            core_role.save(update_fields=["archived_on"])
            self.roles.add(core_role)
        # The circle's policies go: a role only has policies for its domains
        # (1.3.2); the proposal may move them up first
        policies = role.policies.active().filter(domain=None)
        role.archived_policies = list(policies)
        self.policies.update(role.archived_policies)
        policies.update(archived_on=self.day)
        role.is_circle = False
        role.save(update_fields=["is_circle"])

    def finish(self):
        # Circles left without roles of their own turn back into roles
        # automatically, like in GlassFrog 5: a circle of core roles only
        # makes no sense
        from governance.meetings.models import Meeting

        for circle in self.shrunk:
            circle.refresh_from_db()
            if not is_empty_circle(circle):
                continue
            if Meeting.objects.filter(circle=circle).running().exists():
                # Turns back when the meeting ends (revert_after_meeting()),
                # archiving the policies left there (for consequences())
                circle.at_meeting_end = True
                circle.archived_policies = list(
                    circle.policies.active().filter(domain=None)
                )
                self.deferred.append(circle)
                continue
            self.convert(circle, to_circle=False)
            self.reverted.append(circle)
        for role in self.converted:
            sync_circle_role_leads(role, self.day)
        # E.g. a circle without a Circle Lead of its own moved under one its
        # Circle Rep leads (1.4.2)
        for rep in new_reps_leading(self.reps_before):
            self.end_assignment(rep)
            sync_circle_role_leads(rep.role.circle, self.day)
            self.ended_reps.append(rep)


def is_empty_circle(circle):
    """A circle without roles of its own, which turns back into a role"""
    return (
        circle.is_circle
        and circle.circle_id is not None
        and not circle.archived_on
        and not circle.roles.active().exclude(core_role__in=CORE).exists()
    )


@transaction.atomic
def revert_after_meeting(meeting):
    """A circle which lost its last roles while its meeting ran turns back
    into a role when the meeting ends, recorded in the last adopted proposal
    which left it without roles (``Proposal.reverting_circles``)"""
    lock_structure()
    circle = meeting.circle
    if circle is None:
        return
    circle.refresh_from_db()
    if not is_empty_circle(circle):
        return
    proposal = (
        Proposal.objects
        .filter(
            status=Proposal.ADOPTED,
            glassfrog_id=None,
            decided_at__gte=meeting.started_at,
            reverting_circles=circle,
        )
        .order_by("-decided_at", "-pk")
        .first()
    )
    if proposal is None:
        # Not emptied meanwhile, e.g. a role made a circle on purpose
        # holding its first meeting before it has roles
        return
    applier = Applier(proposal)
    # The meeting's outputs tell those losing the core roles about its own
    # proposals; a super-circle's proposal was mailed before, so they hear
    # about it like from an assignment
    own = proposal.meeting_id == meeting.pk
    with nullcontext() if own else announce([circle, circle.circle]):
        applier.convert(circle, to_circle=False)
    proposal.instructions.append({
        "op": "remove",
        "path": f"/roles/{circle.pk}/supporting_circle",
    })
    proposal.names[f"roles/{circle.pk}"] = circle.name
    proposal.save(update_fields=["instructions", "names"])
    proposal.roles.add(circle, *applier.roles)
    proposal.policies.add(*applier.policies)
    if own:
        # For the meeting's outputs; announced otherwise, not again in
        # the mail of a super-circle's meeting still running
        proposal.ended_role_leads.add(*applier.ended_users)
    close_circles([circle], proposal)
    update_changes(since=timezone.localdate())


def role_texts_count(model, role):
    return model.objects.filter(role=role).count()


def replace_keys(proposal, created):
    """Replaces the keys of added objects by their IDs"""
    mapping = {key: f"{key.split('/')[0]}/{obj.pk}" for key, obj in created.items()}

    def replace(path):
        return re.sub(
            r"(roles|policies|accountabilities|domains)/(n\d+)",
            lambda m: mapping.get(m[0], m[0]),
            path,
        )

    proposal.instructions = [
        instruction | {"path": replace(instruction["path"])}
        for instruction in proposal.instructions
    ]
    proposal.names = {replace(key): name for key, name in proposal.names.items()}
    for key, obj in created.items():
        if key.startswith(("roles/", "policies/")):
            proposal.names[mapping[key]] = str(obj)


@transaction.atomic
def adopt(proposal):
    """Applies the proposal and marks it as adopted"""
    # Locked, with its status in the database: two requests (or a click and
    # the hourly task) may adopt the same proposal loaded before. The
    # proposal first, then the structure, like requests changing the
    # proposal before adopting it (the last consent)
    proposal.status = (
        Proposal.objects
        .select_for_update()
        .values_list("status", flat=True)
        .get(pk=proposal.pk)
    )
    lock_structure()
    if proposal.status == Proposal.ADOPTED:
        raise ProposalError([_("The proposal has already been adopted.")])
    if proposal.status == Proposal.WITHDRAWN:
        raise ProposalError([_("The proposal has been withdrawn.")])
    if not proposal.has_changes:
        raise ProposalError([_("A tension without changes isn't adopted.")])
    # Who is affected, before roles are removed or moved away
    before = list(members(proposal.circle).values_list("pk", flat=True))
    applier = Applier(proposal)
    applier.apply(proposal.instructions)
    applier.finish()
    replace_keys(proposal, applier.created)
    for role in applier.made_circles:
        proposal.instructions.insert(
            0, {"op": "add", "path": f"/roles/{role.pk}/supporting_circle"}
        )
        proposal.names[f"roles/{role.pk}"] = role.name
    for circle in applier.reverted:
        # Recorded, so that the proposal's diff and the history show it
        step = {"op": "remove", "path": f"/roles/{circle.pk}/supporting_circle"}
        if step not in proposal.instructions:  # Unless done on purpose
            proposal.instructions.append(step)
        proposal.names[f"roles/{circle.pk}"] = circle.name
    proposal.status = Proposal.ADOPTED
    proposal.decided_at = timezone.now()
    proposal.save()
    # The circles turning back when their meeting ends, for
    # revert_after_meeting()
    proposal.roles.add(*applier.roles, *applier.deferred)
    proposal.reverting_circles.add(*applier.deferred)
    proposal.policies.add(*applier.policies)
    # For the mails (assignments started today are deleted)
    proposal.ended_role_leads.add(*applier.ended_users)
    close_circles([*applier.removed, *applier.reverted], proposal)
    update_changes(since=timezone.localdate())
    from governance.proposals.process import recheck_conflicts

    recheck_conflicts(proposal)
    if not (proposal.meeting and proposal.meeting.is_running):
        # The meeting mails its outputs together when it ends
        transaction.on_commit(partial(mails.proposal_adopted, proposal, before))
    return proposal


def close_circles(circles, adopted):
    """Circles and roles removed, circles turned back into roles: their open
    proposals (also those for inside a role) are withdrawn, their running
    meetings end"""
    from governance.meetings.activity import end_meeting
    from governance.meetings.models import Meeting
    from governance.proposals.process import withdraw

    if not circles:
        return
    proposals = Proposal.objects.filter(circle__in=circles).exclude(
        status__in=[Proposal.ADOPTED, Proposal.WITHDRAWN]
    )
    if adopted is not None:
        proposals = proposals.exclude(pk=adopted.pk)
    for proposal in proposals.select_related("circle", "proposer"):
        withdraw(proposal)
        # Their proposers learn why
        transaction.on_commit(partial(mails.proposal_withdrawn, proposal, adopted))
    for meeting in Meeting.objects.filter(circle__in=circles).running():
        end_meeting(meeting)


def consequences(proposal):
    """What adopting the proposal does automatically: the circles turning
    back into roles because they lose their last roles (``reverting``), the
    Circle Reps resigning because they'd lead their circle (``reps``)"""
    applier = Applier(proposal)
    try:
        with transaction.atomic():
            applier.apply(proposal.instructions)
            applier.finish()
            raise Rollback
    except ProposalError:
        return {}
    except Rollback:
        return {
            "reverting": [*applier.reverted, *applier.deferred],
            "reps": applier.ended_reps,
        }


def problems(proposal):
    """Conflicts and violations adopting the proposal now would find"""
    try:
        with transaction.atomic():
            Applier(proposal).apply(proposal.instructions)
            raise Rollback
    except ProposalError as exc:
        return exc.problems
    except Rollback:
        return []


OPS = {"add", "replace", "remove", "move", "test"}


def validate_format(instructions):
    """Problems with the format of instructions coming from outside"""
    if not isinstance(instructions, list):
        return [_("The instructions have to be a list.")]
    found = []
    for index, instruction in enumerate(instructions, 1):
        if (
            not isinstance(instruction, dict)
            or instruction.get("op") not in OPS
            or not isinstance(instruction.get("path"), str)
            or not instruction["path"].startswith("/")
            or not isinstance(instruction.get("from", ""), str)
        ):
            found.append(
                _("Instruction %(number)s needs an op (%(ops)s) and a path.")
                % {"number": index, "ops": ", ".join(sorted(OPS))}
            )
        elif any(
            not isinstance(instruction.get(key), str | None)
            for key in ["value", "original_value"]
        ):
            found.append(
                _("The values of instruction %(number)s have to be texts.")
                % {"number": index}
            )
    return found


def names_for(instructions):
    """The current names of the objects the instructions refer to, and the
    names of the objects they add"""
    names = {}
    models = {"roles": Role, "circles": Role, "policies": Policy}
    for instruction in instructions:
        for text in [instruction["path"], instruction.get("from", "")]:
            for kind, key in re.findall(
                r"(roles|circles|policies|accountabilities|domains)/(\d+)", text
            ):
                if f"{kind}/{key}" in names:
                    continue
                if kind in models:
                    obj = models[kind].objects.filter(pk=key).first()
                else:
                    obj = TEXTS[kind].objects.filter(pk=key).first()
                if obj is not None:
                    names[f"{kind}/{key}"] = str(obj)
        if match := re.fullmatch(
            r"/(roles|policies)/(n\d+)/(name|title)", instruction["path"]
        ):
            names[f"{match[1]}/{match[2]}"] = instruction.get("value") or ""
    return names
