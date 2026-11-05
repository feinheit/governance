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

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from governance.history.update import update_changes
from governance.notifications.mails import proposal_adopted
from governance.proposals.models import Proposal
from governance.roles.assignments import end_assignment, sync_circle_holders
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
        # Roles and circles removed, also those inside removed circles
        self.removed = []
        self.made_circles = []  # Automatically, by adding roles inside

    def problem(self, message, **kwargs):
        # Once, even if several instructions refer to the missing role
        if (problem := message % kwargs) not in self.problems:
            self.problems.append(problem)

    def get(self, kind, key, *, allow_archived=False, circle=None):
        """The role or policy of a path, checked against the circle"""
        circle = circle or self.circle
        if NEW_KEY.fullmatch(key):
            obj = self.created.get(f"{kind}/{key}")
            if obj is None:
                self.problem(
                    _("The proposal refers to %(key)s before adding it."), key=key
                )
            return obj
        model = Role if kind == "roles" else Policy
        obj = model.objects.filter(pk=key).first()
        if obj is None or (obj.archived_on and not allow_archived):
            self.problem(
                _("%(object)s doesn't exist anymore."),
                object=self.proposal.names.get(f"{kind}/{key}") or f"{kind}/{key}",
            )
            return None
        if kind == "roles":
            # The anchor circle governs its own purpose and accountabilities
            # (constitution 1.3.3), other roles are governed by their circle
            owner = obj.pk if obj.circle_id is None else obj.circle_id
        else:
            owner = obj.role_id if obj.role.is_circle else obj.role.circle_id
        if owner != circle.pk:
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
        for instruction in instructions:
            self.apply_one(instruction)
        for kind, obj in self.created.items():
            if kind.startswith(("roles/", "policies/")) and not str(obj).strip():
                self.problem(_("A new role or policy needs a name."))
        if self.problems:
            raise ProposalError(self.problems)

    def apply_one(self, instruction):  # noqa: C901
        op, path = instruction["op"], instruction["path"]
        value = instruction.get("value")

        if op == "move":
            self.move(instruction)
            return

        if match := re.fullmatch(rf"/(roles|policies)/{KEY}", path):
            kind, key = match[1], match[2]
            if op == "test":
                self.get(kind, key)
            elif op == "add":
                if kind == "roles":
                    # Roles inside a role make it a circle (constitution
                    # 1.3.1), recorded when adopting
                    self.make_circle(self.circle)
                    obj = Role.objects.create(circle=self.circle, name="")
                    self.roles.add(obj)
                else:
                    obj = Policy.objects.create(role=self.circle, title="")
                    self.policies.add(obj)
                self.created[f"{kind}/{key}"] = obj
            elif op == "remove":
                obj = self.get(kind, key)
                if obj is not None:
                    self.remove(obj)
            else:
                self.unsupported(path)
            return

        if match := re.fullmatch(rf"/roles/{KEY}/(name|aim)", path):
            role = self.get("roles", match[1])
            if role is None:
                return
            if role.core_role:
                self.problem(_("The constitution defines %(role)s."), role=role)
                return
            field = ROLE_FIELDS[match[2]]
            label = f"{role}: {field}"
            if self.check_value(label, value) and self.check_original(
                label, getattr(role, field), instruction
            ):
                setattr(role, field, value or "")
                role.save(update_fields=[field])
            return

        if match := re.fullmatch(rf"/policies/{KEY}/(title|body)", path):
            policy = self.get("policies", match[1])
            if policy is None:
                return
            field = POLICY_FIELDS[match[2]]
            label = f"{policy}: {field}"
            if self.check_value(label, value) and self.check_original(
                label, getattr(policy, field), instruction
            ):
                setattr(policy, field, value or "")
                policy.save(update_fields=[field])
            return

        if match := re.fullmatch(
            rf"/roles/{KEY}/(accountabilities|domains)/{KEY}(?:/description)?", path
        ):
            role = self.get("roles", match[1])
            if role is None:
                return
            if role.core_role == LEAD:
                # Additions would apply to all sub-circles' Circle Leads
                # (constitution 1.4.5); the app leaves the Circle Lead as
                # the constitution defines it, on purpose
                self.problem(_("The Circle Lead gets no accountabilities or domains."))
                return
            model = TEXTS[match[2]]
            if not self.check_value(str(role), value):
                return
            if op == "add":
                obj = model.objects.create(
                    role=role,
                    text=value or "",
                    position=role_texts_count(model, role),
                )
                self.created[f"{match[2]}/{match[3]}"] = obj
                return
            obj = model.objects.filter(pk=match[3], role=role).first()
            if obj is None:
                self.problem(
                    _("%(text)s doesn't exist anymore."),
                    text=instruction.get("original_value") or path,
                )
            elif self.check_original(f"{role}: {obj}", obj.text, instruction):
                if op == "remove":
                    if model is Domain:
                        # The role's policies regulating it go with it
                        policies = obj.policies.active()
                        self.policies.update(policies)
                        policies.update(archived_on=self.day)
                    obj.delete()
                elif op == "replace":
                    obj.text = value or ""
                    obj.save(update_fields=["text"])
                else:
                    self.unsupported(path)
            return

        if match := re.fullmatch(rf"/roles/{KEY}/supporting_circle", path):
            role = self.get("roles", match[1])
            if role is not None:
                self.convert(role, to_circle=op == "add")
            return

        self.unsupported(path)

    def move(self, instruction):
        """Moves a role or policy into a sub-circle, or out of one"""
        path, source = instruction["path"], instruction.get("from", "")
        if match := re.fullmatch(
            rf"/roles/{KEY}/supporting_circle/(roles|policies)/{KEY}", path
        ):
            target = self.get("roles", match[1])
            obj = self.get(match[2], match[3])
            kind = match[2]
        elif (match := re.fullmatch(rf"/(roles|policies)/{KEY}", path)) and (
            source_match := re.fullmatch(
                rf"/circles/{KEY}/(roles|policies)/{KEY}", source
            )
        ):
            kind = match[1]
            source_circle = self.get("roles", source_match[1])
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
        if not target.is_circle and kind == "roles" and not target.core_role:
            # Moving roles into a role makes it a circle
            self.make_circle(target)
        if not target.is_circle:
            self.problem(_("%(role)s isn't a circle."), role=target)
        elif kind == "roles":
            if obj.core_role or obj == target or obj.circle_id is None:
                self.problem(_("%(role)s can't be moved."), role=obj)
                return
            self.shrunk.add(obj.circle)
            obj.circle = target
            obj.save(update_fields=["circle"])
        elif not obj.role.is_circle:
            # Policies of roles for their domains go with the role
            self.problem(_("%(policy)s can't be moved."), policy=obj)
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
            end_assignment(assignment, self.day)
        role.archived_on = self.day
        role.save(update_fields=["archived_on"])
        role.policies.active().update(archived_on=self.day)
        self.removed.append(role)

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
            # The role's holders lead the new circle
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
        for core_role in role.roles.active():
            for assignment in Assignment.objects.current().filter(role=core_role):
                end_assignment(assignment, self.day)
            core_role.archived_on = self.day
            core_role.save(update_fields=["archived_on"])
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
        for circle in self.shrunk:
            circle.refresh_from_db()
            if (
                circle.is_circle
                and circle.circle_id
                and not circle.archived_on
                and not circle.roles.active().exclude(core_role__in=CORE).exists()
            ):
                self.convert(circle, to_circle=False)
                self.reverted.append(circle)
        for role in self.converted:
            sync_circle_holders(role, self.day)


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
    if proposal.glassfrog_id or proposal.status == Proposal.ADOPTED:
        raise ProposalError([_("The proposal has already been adopted.")])
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
        proposal.instructions.append({
            "op": "remove",
            "path": f"/roles/{circle.pk}/supporting_circle",
        })
        proposal.names[f"roles/{circle.pk}"] = circle.name
    proposal.status = Proposal.ADOPTED
    proposal.decided_at = timezone.now()
    proposal.save()
    proposal.roles.add(*applier.roles)
    proposal.policies.add(*applier.policies)
    close_circles([*applier.removed, *applier.reverted], proposal)
    update_changes(since=timezone.localdate())
    if not (proposal.meeting and proposal.meeting.is_running):
        # The meeting mails its outputs together when it ends
        transaction.on_commit(lambda: proposal_adopted(proposal, before))
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
    for proposal in (
        Proposal.objects
        .filter(circle__in=circles)
        .exclude(status__in=[Proposal.ADOPTED, Proposal.WITHDRAWN])
        .exclude(pk=adopted.pk)
    ):
        withdraw(proposal)
    for meeting in Meeting.objects.filter(circle__in=circles).running():
        end_meeting(meeting)


def consequences(proposal):
    """What adopting the proposal does automatically: the circles turning
    back into roles because they lose their last roles"""
    applier = Applier(proposal)
    try:
        with transaction.atomic():
            applier.apply(proposal.instructions)
            applier.finish()
            raise Rollback
    except ProposalError:
        return []
    except Rollback:
        return applier.reverted


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
        ):
            found.append(
                _("Instruction %(number)s needs an op (%(ops)s) and a path.")
                % {"number": index, "ops": ", ".join(sorted(OPS))}
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
