"""Whole meetings through the views, one proposal after the other

The single steps are tested in ``test_processing`` and in the proposals'
tests; here the proposals build on each other: the IDs of roles added
earlier, circles made by moving roles, the history and the outputs of the
whole meeting.
"""

import datetime as dt

import time_machine
from django.core import mail
from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.utils import timezone

from governance.accounts.models import User
from governance.history.audit import structure_from_database, structure_on
from governance.history.backfill import backfill
from governance.history.models import Change
from governance.meetings.activity import end_meeting
from governance.meetings.models import AgendaItem, Meeting
from governance.proposals.instructions import adopt
from governance.proposals.models import Proposal
from governance.roles.models import Accountability, Assignment, Policy, Role


class GovernanceMeetingScenarioTest(TestCase):
    def setUp(self):
        self.ada = User.objects.create_user("ada@example.com", full_name="Ada")
        self.bob = User.objects.create_user("bob@example.com", full_name="Bob")
        self.eve = User.objects.create_user("eve@example.com", full_name="Eve")
        self.kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        self.kitchen.create_core_roles()
        Assignment.objects.create(
            role=self.kitchen.roles.get(core_role="facilitator"), user=self.ada
        )
        Assignment.objects.create(
            role=self.kitchen.roles.get(core_role="secretary"), user=self.bob
        )
        self.cook = Role.objects.create(name="Cook", circle=self.kitchen)
        Assignment.objects.create(role=self.cook, user=self.eve)
        self.tea = Policy.objects.create(role=self.kitchen, title="Tea")

        self.bakery = Role.objects.create(
            name="Bakery", circle=self.kitchen, is_circle=True
        )
        self.bakery.create_core_roles()
        self.baker = Role.objects.create(name="Baker", circle=self.bakery)
        self.cleaner = Role.objects.create(name="Cleaner", circle=self.bakery)
        Assignment.objects.create(role=self.cleaner, user=self.eve)
        self.oven = Role.objects.create(name="Oven", circle=self.bakery, is_circle=True)
        self.oven.create_core_roles()
        self.heater = Role.objects.create(name="Heater", circle=self.oven)
        self.flour = Policy.objects.create(role=self.bakery, title="Flour")
        self.noise = Policy.objects.create(role=self.bakery, title="Noise")

        # The structure until yesterday, the meeting's changes are today's
        self.yesterday = timezone.localdate() - dt.timedelta(days=1)
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM audit_logged_actions")
        backfill([(self.yesterday, structure_from_database(self.yesterday))])

    def proposal(self, meeting, label):
        """The secretary captures a proposal for a tension in the meeting"""
        self.client.force_login(self.bob)
        self.client.post(f"/meetings/{meeting.pk}/agenda/add/", {"label": label})
        item = AgendaItem.objects.get(meeting=meeting, label=label)
        self.client.post(f"/agenda/{item.pk}/process/")
        self.client.post(f"/agenda/{item.pk}/proposal/")
        item.refresh_from_db()
        return item, item.proposal

    def adopt(self, item):
        self.client.force_login(self.bob)  # The secretary
        response = self.client.post(f"/agenda/{item.pk}/adopt/", follow=True)
        self.assertContains(response, "The proposal is adopted.")
        item.proposal.refresh_from_db()
        self.assertEqual(item.proposal.status, Proposal.ADOPTED)

    def test_restructuring(self):
        self.client.force_login(self.bob)
        self.client.post(f"/roles/{self.kitchen.pk}/meetings/new/")
        meeting = Meeting.objects.get()

        # A new role
        item, proposal = self.proposal(meeting, "Pastry")
        self.client.post(
            f"/proposals/{proposal.pk}/roles/new/",
            {
                "name": "Pastry",
                "purpose": "Sweet things",
                "new_accountabilities": "Icing cakes",
            },
        )
        self.adopt(item)
        pastry = Role.objects.get(name="Pastry")
        self.assertEqual((pastry.circle, pastry.is_circle), (self.kitchen, False))

        # Moving a role into it makes it a circle
        item, proposal = self.proposal(meeting, "Cakes need a cook")
        self.client.post(
            f"/proposals/{proposal.pk}/move/",
            {"kind": "roles", "key": self.cook.pk, "target": pastry.pk},
        )
        self.adopt(item)
        pastry.refresh_from_db()
        self.cook.refresh_from_db()
        self.assertTrue(pastry.is_circle)
        self.assertEqual(self.cook.circle, pastry)
        # Eve still holds Cook, and leads Pastry through it
        self.assertTrue(
            Assignment.objects.current().filter(role=self.cook, user=self.eve).exists()
        )

        # A policy into the new circle; the bakery goes, some of it stays
        item, proposal = self.proposal(meeting, "No more bakery")
        self.client.post(
            f"/proposals/{proposal.pk}/move/",
            {"kind": "policies", "key": self.tea.pk, "target": pastry.pk},
        )
        self.client.post(
            f"/proposals/{proposal.pk}/roles/{self.bakery.pk}/remove-circle/",
            {"roles": [self.baker.pk], "policies": [self.flour.pk]},
        )
        self.adopt(item)

        # Cook belongs to Pastry now: Kitchen's proposals don't change it
        item, proposal = self.proposal(meeting, "Cook again")
        self.assertEqual(
            self.client.get(
                f"/proposals/{proposal.pk}/roles/{self.cook.pk}/"
            ).status_code,
            404,
        )
        self.client.post(f"/agenda/{item.pk}/complete/")

        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(f"/meetings/{meeting.pk}/end/")

        # The structure
        for obj in [
            self.tea,
            self.bakery,
            self.baker,
            self.cleaner,
            self.oven,
            self.heater,
            self.flour,
            self.noise,
        ]:
            obj.refresh_from_db()
        self.assertEqual((self.tea.role, self.tea.archived_on), (pastry, None))
        self.assertEqual(
            (self.baker.circle, self.baker.archived_on), (self.kitchen, None)
        )
        self.assertEqual(
            (self.flour.role, self.flour.archived_on), (self.kitchen, None)
        )
        for obj in [self.bakery, self.cleaner, self.oven, self.heater, self.noise]:
            self.assertEqual(obj.archived_on, timezone.localdate(), obj)
        self.assertFalse(
            Assignment.objects.current().filter(role=self.cleaner).exists()
        )
        self.assertEqual(
            list(pastry.accountabilities.values_list("text", flat=True)),
            ["Icing cakes"],
        )

        # The history: the past day and today's changes
        before, after = structure_on(self.yesterday), structure_on(timezone.localdate())
        self.assertEqual(before["roles"][str(self.cook.pk)]["circle"], self.kitchen.pk)
        self.assertEqual(after["roles"][str(self.cook.pk)]["circle"], pastry.pk)
        self.assertNotIn(str(self.bakery.pk), after["roles"])
        changes = {
            (change.policy or change.role, change.kind)
            for change in Change.objects.filter(date=timezone.localdate())
        }
        # From day to day: Pastry is new today, not a role made a circle;
        # the roles removed with the bakery lose their Role Leads with them
        self.assertLessEqual(
            {
                (pastry, "added"),
                (self.cook, "moved"),
                (self.baker, "moved"),
                (self.bakery, "removed"),
                (self.cleaner, "removed"),
                (self.oven, "removed"),
                (self.heater, "removed"),
                (self.tea, "policy-moved"),
                (self.flour, "policy-moved"),
                (self.noise, "policy-removed"),
            },
            changes,
        )
        self.assertNotIn((self.cook, "unassigned"), changes)

        # The outputs: the adopted proposals, not the one without
        body = mail.outbox[0].body
        for label in ["Pastry", "Cakes need a cook", "No more bakery"]:
            self.assertIn(f"Adopted: {label}", body)
        self.assertNotIn("Cook again", body)

    def test_role_made_a_circle_holds_its_first_meeting(self):
        """A role turned into a circle on purpose has no roles yet: its first
        meeting ending without adding any doesn't turn it back, only losing
        its last roles does"""
        self.client.force_login(self.bob)
        self.client.post(f"/roles/{self.kitchen.pk}/meetings/new/")
        meeting = Meeting.objects.get()
        item, proposal = self.proposal(meeting, "Cooking grows")
        self.client.post(f"/proposals/{proposal.pk}/roles/{self.cook.pk}/convert/")
        self.adopt(item)
        with self.captureOnCommitCallbacks(execute=True):
            end_meeting(meeting)
        self.cook.refresh_from_db()
        self.assertTrue(self.cook.is_circle)

        # Eve leads it, its first meeting elects its Secretary
        first = Meeting.objects.create(
            circle=self.cook, kind=Meeting.GOVERNANCE, started_at=timezone.now()
        )
        secretary = self.cook.roles.get(core_role="secretary")
        Assignment.objects.create(role=secretary, user=self.eve)
        with self.captureOnCommitCallbacks(execute=True):
            end_meeting(first)
        self.cook.refresh_from_db()
        self.assertTrue(self.cook.is_circle)
        self.assertTrue(Assignment.objects.current().filter(role=secretary).exists())


class AsyncAndMeetingScenarioTest(TestCase):
    """An async proposal and a meeting change the same accountability: at
    the deadline the async one goes to the meeting, the secretary merges"""

    def setUp(self):
        self.ada = User.objects.create_user("ada@example.com", full_name="Ada")
        self.bob = User.objects.create_user("bob@example.com", full_name="Bob")
        self.eve = User.objects.create_user("eve@example.com", full_name="Eve")
        self.kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        self.kitchen.create_core_roles()
        Assignment.objects.create(
            role=self.kitchen.roles.get(core_role="facilitator"), user=self.ada
        )
        Assignment.objects.create(
            role=self.kitchen.roles.get(core_role="secretary"), user=self.bob
        )
        self.cook = Role.objects.create(name="Cook", circle=self.kitchen)
        Assignment.objects.create(role=self.cook, user=self.eve)
        self.cooking = Accountability.objects.create(role=self.cook, text="Cooking")

    def change_cooking(self, proposal, text):
        response = self.client.post(
            f"/proposals/{proposal.pk}/roles/{self.cook.pk}/",
            {
                "name": "Cook",
                "purpose": "",
                f"accountabilities-{self.cooking.pk}": text,
            },
        )
        self.assertEqual(response.status_code, 302)

    def meeting(self):
        self.client.force_login(self.bob)
        self.client.post(f"/roles/{self.kitchen.pk}/meetings/new/")
        return Meeting.objects.running().get()

    def test_async_after_the_meeting(self):
        start = timezone.now()
        # Eve publishes her change
        self.client.force_login(self.eve)
        self.client.post(
            f"/roles/{self.kitchen.pk}/proposals/new/",
            {"role": self.cook.pk, "tension": "Meals, not food"},
        )
        async_proposal = Proposal.objects.get()
        self.change_cooking(async_proposal, "Cooking meals")
        self.client.post(f"/proposals/{async_proposal.pk}/publish/")
        async_proposal.refresh_from_db()
        self.assertEqual(async_proposal.status, Proposal.PUBLISHED)

        # Meanwhile a meeting changes the same accountability
        meeting = self.meeting()
        self.client.post(f"/meetings/{meeting.pk}/agenda/add/", {"label": "Food"})
        item = AgendaItem.objects.get(label="Food")
        self.client.post(f"/agenda/{item.pk}/process/")
        self.client.post(f"/agenda/{item.pk}/proposal/")
        item.refresh_from_db()
        self.change_cooking(item.proposal, "Cooking food")
        self.client.force_login(self.bob)
        self.client.post(f"/agenda/{item.pk}/adopt/")
        self.client.post(f"/meetings/{meeting.pk}/end/")
        self.cooking.refresh_from_db()
        self.assertEqual(self.cooking.text, "Cooking food")

        # The deadline passes: the async proposal conflicts, it waits for a
        # meeting instead of being adopted
        with time_machine.travel(start + dt.timedelta(days=5), tick=False):
            call_command("fairy_tasks")
            async_proposal.refresh_from_db()
            self.assertEqual(
                (async_proposal.status, async_proposal.meeting),
                (Proposal.IN_MEETING, None),
            )
            self.cooking.refresh_from_db()
            self.assertEqual(self.cooking.text, "Cooking food")

            # The next meeting: the secretary merges both versions
            meeting = self.meeting()
            self.client.post(
                f"/meetings/{meeting.pk}/agenda/add/", {"proposal": async_proposal.pk}
            )
            item = AgendaItem.objects.get(proposal=async_proposal)
            self.client.post(f"/agenda/{item.pk}/process/")
            self.assertContains(
                self.client.get(meeting.get_absolute_url()),
                "has been changed since the proposal was drafted",
            )
            url = f"/proposals/{async_proposal.pk}/roles/{self.cook.pk}/"
            form = self.client.get(url).context["form"]
            name = f"accountabilities-{self.cooking.pk}"
            self.assertEqual(
                form[name].initial,
                "<<<<<<< currently\nCooking food\n=======\nCooking meals\n"
                ">>>>>>> proposal",
            )
            self.change_cooking(async_proposal, "Cooking food and meals")
            self.client.force_login(self.bob)
            response = self.client.post(f"/agenda/{item.pk}/adopt/", follow=True)
            self.assertContains(response, "The proposal is adopted.")

        async_proposal.refresh_from_db()
        self.cooking.refresh_from_db()
        self.assertEqual(
            (async_proposal.status, async_proposal.meeting),
            (Proposal.ADOPTED, meeting),
        )
        self.assertEqual(self.cooking.text, "Cooking food and meals")


class CircleEndsItselfScenarioTest(TestCase):
    def test_last_role_removed_in_its_own_meeting(self):
        """The bakery's meeting removes its last role: the meeting goes on to
        its closing round, the bakery turns back into a role when it ends,
        its other proposals are withdrawn then, the attendees get the
        outputs"""
        ada = User.objects.create_user("ada@example.com", full_name="Ada")
        bob = User.objects.create_user("bob@example.com", full_name="Bob")
        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        kitchen.create_core_roles()
        bakery = Role.objects.create(name="Bakery", is_circle=True, circle=kitchen)
        bakery.create_core_roles()
        Assignment.objects.create(
            role=bakery.roles.get(core_role="facilitator"), user=ada
        )
        Assignment.objects.create(
            role=bakery.roles.get(core_role="secretary"), user=bob
        )
        baker = Role.objects.create(name="Baker", circle=bakery)
        other = Proposal.objects.create(
            circle=bakery,
            proposer=bob,
            tension="Ovens",
            status=Proposal.PUBLISHED,
            created_at=timezone.now(),
        )

        self.client.force_login(bob)  # The Secretary starts it
        self.client.post(f"/roles/{bakery.pk}/meetings/new/")
        meeting = Meeting.objects.running().get()
        self.client.post(f"/meetings/{meeting.pk}/agenda/add/", {"label": "Bread"})
        item = AgendaItem.objects.get(meeting=meeting, label="Bread")
        self.client.force_login(bob)  # The secretary
        self.client.post(f"/agenda/{item.pk}/process/")
        self.client.post(f"/agenda/{item.pk}/proposal/")
        item.refresh_from_db()
        self.client.post(f"/proposals/{item.proposal.pk}/roles/{baker.pk}/remove/")
        self.client.force_login(ada)
        response = self.client.get(meeting.get_absolute_url())
        self.assertContains(response, "Bakery loses its last roles")
        self.assertContains(response, "when the meeting ends")
        self.client.force_login(bob)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(f"/agenda/{item.pk}/adopt/", follow=True)
        self.assertContains(response, "The proposal is adopted.")

        # The meeting goes on, to its closing round
        for obj in [bakery, meeting, item, item.proposal, other]:
            obj.refresh_from_db()
        self.assertEqual(
            (item.proposal.status, item.is_completed), (Proposal.ADOPTED, True)
        )
        self.assertTrue(bakery.is_circle)
        self.assertIsNone(meeting.ended_at)
        self.assertEqual(other.status, Proposal.PUBLISHED)
        self.client.post(f"/meetings/{meeting.pk}/step/", {"step": "closing"})
        meeting.refresh_from_db()
        self.assertEqual(meeting.step, "closing")
        self.assertEqual(
            [m for m in mail.outbox if "Bread" in m.body], []
        )  # Not before the end

        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(f"/meetings/{meeting.pk}/end/")
        for obj in [bakery, meeting, item.proposal, other]:
            obj.refresh_from_db()
        self.assertFalse(bakery.is_circle)
        self.assertIsNotNone(meeting.ended_at)
        self.assertEqual(other.status, Proposal.WITHDRAWN)
        self.assertFalse(
            Assignment.objects.current().filter(role__circle=bakery).exists()
        )
        # The proposal records the step, its diff and the history show it
        self.assertIn(
            {"op": "remove", "path": f"/roles/{bakery.pk}/supporting_circle"},
            item.proposal.instructions,
        )
        outputs = [m for m in mail.outbox if m.subject.startswith("Outputs")]
        self.assertEqual(
            sorted(m.to[0] for m in outputs), ["ada@example.com", "bob@example.com"]
        )
        # The outputs tell them, no mail about their roles besides
        self.assertFalse([m for m in mail.outbox if m.subject.startswith("Your roles")])
        # Bob's other proposal was withdrawn with the bakery
        self.assertIn(
            ("bob@example.com", "Withdrawn: Ovens"),
            [(m.to[0], m.subject) for m in mail.outbox],
        )

    def test_roles_added_again_before_the_end(self):
        """A circle whose meeting removes its last role and adds another one
        stays a circle"""
        ada = User.objects.create_user("ada@example.com", full_name="Ada")
        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        kitchen.create_core_roles()
        bakery = Role.objects.create(name="Bakery", is_circle=True, circle=kitchen)
        bakery.create_core_roles()
        Assignment.objects.create(
            role=bakery.roles.get(core_role="secretary"), user=ada
        )
        baker = Role.objects.create(name="Baker", circle=bakery)
        meeting = Meeting.objects.create(
            circle=bakery,
            kind=Meeting.GOVERNANCE,
            started_at=timezone.now(),
            secretary=ada,
        )
        for instructions in [
            [{"op": "remove", "path": f"/roles/{baker.pk}"}],
            [
                {"op": "add", "path": "/roles/n1"},
                {"op": "add", "path": "/roles/n1/name", "value": "Pastry Chef"},
            ],
        ]:
            adopt(
                Proposal.objects.create(
                    circle=bakery,
                    proposer=ada,
                    tension="Bread",
                    status=Proposal.IN_MEETING,
                    meeting=meeting,
                    instructions=instructions,
                    created_at=timezone.now(),
                )
            )
        end_meeting(meeting)
        bakery.refresh_from_db()
        self.assertTrue(bakery.is_circle)


class RoleMeetingScenarioTest(TestCase):
    def test_role_leads_break_down_their_role(self):
        """The inside of every role is a circle (1.3.1): its Role Leads hold
        governance meetings there, adding roles makes it a circle"""
        ada = User.objects.create_user("ada@example.com", full_name="Ada")
        bob = User.objects.create_user("bob@example.com", full_name="Bob")
        eve = User.objects.create_user("eve@example.com", full_name="Eve")
        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        kitchen.create_core_roles()
        cook = Role.objects.create(name="Cook", circle=kitchen)
        for user in [ada, bob]:
            Assignment.objects.create(role=cook, user=user)
        Assignment.objects.create(
            role=Role.objects.create(name="Waiter", circle=kitchen), user=eve
        )
        # The kitchen's Circle Lead isn't in the cook's inner circle
        zoe = User.objects.create_user("zoe@example.com", full_name="Zoe")
        Assignment.objects.create(role=kitchen.roles.get(core_role="lead"), user=zoe)

        # Not for others, and no tactical meetings in a role
        self.client.force_login(eve)
        self.assertNotContains(
            self.client.get(cook.get_absolute_url()), "Start a governance meeting"
        )
        self.assertEqual(
            self.client.post(f"/roles/{cook.pk}/meetings/new/").status_code, 403
        )
        self.client.force_login(ada)
        # Asked first, in a modal on the role's page; cancelling is the
        # default (the primary button, focused)
        url = f"/roles/{cook.pk}/meetings/new/"
        response = self.client.get(cook.get_absolute_url())
        self.assertRegex(response.content.decode(), rf'href="{url}"\s+data-modal')
        response = self.client.get(
            url, headers={"hx-request": "true", "hx-modal": "true"}
        )
        self.assertContains(
            response, "Really start a governance meeting in the role Cook?"
        )
        self.assertRegex(
            response.content.decode(),
            r'class="btn btn-primary"\s+data-modal-close\s+autofocus',
        )
        self.assertFalse(Meeting.objects.exists())
        self.assertEqual(
            self.client.post(
                f"/roles/{cook.pk}/meetings/new/", {"kind": "tactical"}
            ).status_code,
            403,
        )

        self.client.post(f"/roles/{cook.pk}/meetings/new/")
        meeting = Meeting.objects.get()
        self.assertEqual(
            (meeting.circle, meeting.kind, set(meeting.attendees.all())),
            (cook, Meeting.GOVERNANCE, {ada, bob}),
        )
        # Somebody of the inner circle is the secretary, not the kitchen's lead
        self.assertIn(meeting.secretary, {ada, bob})
        self.client.post(f"/meetings/{meeting.pk}/agenda/add/", {"label": "Help"})
        item = AgendaItem.objects.get()
        self.client.post(f"/agenda/{item.pk}/process/")
        self.client.post(f"/agenda/{item.pk}/proposal/")
        item.refresh_from_db()
        self.assertEqual(item.proposal.role, cook)
        self.client.post(
            f"/proposals/{item.proposal.pk}/roles/new/",
            {"name": "Sous", "purpose": "", "new_accountabilities": "Chopping"},
        )
        # A second one, drafted before the first makes the role a circle
        self.client.post(f"/meetings/{meeting.pk}/agenda/add/", {"label": "Dishes"})
        second = AgendaItem.objects.get(label="Dishes")
        self.client.post(f"/agenda/{second.pk}/process/")
        self.client.post(f"/agenda/{second.pk}/proposal/")
        second.refresh_from_db()
        self.client.post(
            f"/proposals/{second.proposal.pk}/roles/new/",
            {"name": "Dishwasher", "purpose": ""},
        )
        self.client.post(f"/agenda/{item.pk}/process/")
        response = self.client.post(f"/agenda/{item.pk}/adopt/", follow=True)
        self.assertContains(response, "The proposal is adopted.")
        # From the role, now its Circle Lead
        self.client.post(f"/agenda/{second.pk}/process/")
        response = self.client.post(f"/agenda/{second.pk}/adopt/", follow=True)
        self.assertContains(response, "The proposal is adopted.")
        second.proposal.refresh_from_db()
        self.assertEqual(second.proposal.role, cook.roles.get(core_role="lead"))

        cook.refresh_from_db()
        self.assertTrue(cook.is_circle)
        self.assertEqual(Role.objects.get(name="Sous").circle, cook)
        lead = cook.roles.get(core_role="lead")
        self.assertEqual(
            set(
                Assignment.objects
                .current()
                .filter(role=lead)
                .values_list("user", flat=True)
            ),
            {ada.pk, bob.pk},
        )
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(f"/meetings/{meeting.pk}/end/")
        self.assertEqual(
            sorted(m.to[0] for m in mail.outbox), ["ada@example.com", "bob@example.com"]
        )
        self.assertEqual(
            self.client.get(f"/roles/{cook.pk}/meetings/").status_code, 200
        )


class CircleEmptiedFromAboveScenarioTest(TestCase):
    def test_super_circle_moves_the_last_role_out(self):
        """The kitchen moves the bakery's last role out while the bakery's
        meeting runs: the bakery turns back into a role when its meeting
        ends, the kitchen's proposal records it"""
        ada = User.objects.create_user("ada@example.com", full_name="Ada")
        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        kitchen.create_core_roles()
        bakery = Role.objects.create(name="Bakery", is_circle=True, circle=kitchen)
        bakery.create_core_roles()
        baker = Role.objects.create(name="Baker", circle=bakery)
        meeting = Meeting.objects.create(
            circle=bakery, kind=Meeting.GOVERNANCE, started_at=timezone.now()
        )
        moving = adopt(
            Proposal.objects.create(
                circle=kitchen,
                proposer=ada,
                tension="Bread",
                status=Proposal.PUBLISHED,
                instructions=[
                    {
                        "op": "move",
                        "from": f"/circles/{bakery.pk}/roles/{baker.pk}",
                        "path": f"/roles/{baker.pk}",
                    }
                ],
                created_at=timezone.now(),
            )
        )
        bakery.refresh_from_db()
        self.assertTrue(bakery.is_circle)

        # A later proposal renaming the bakery doesn't record it
        renaming = adopt(
            Proposal.objects.create(
                circle=kitchen,
                proposer=ada,
                tension="Name",
                status=Proposal.PUBLISHED,
                instructions=[
                    {
                        "op": "replace",
                        "path": f"/roles/{bakery.pk}/name",
                        "original_value": "Bakery",
                        "value": "Bread",
                    }
                ],
                created_at=timezone.now(),
            )
        )

        end_meeting(meeting)
        bakery.refresh_from_db()
        moving.refresh_from_db()
        renaming.refresh_from_db()
        self.assertEqual(len(renaming.instructions), 1)
        self.assertFalse(bakery.is_circle)
        self.assertIn(
            {"op": "remove", "path": f"/roles/{bakery.pk}/supporting_circle"},
            moving.instructions,
        )

    def test_circle_rep_leaves_the_role(self):
        """A circle turned back into a role keeps its Circle Leads as Role Leads,
        not its Circle Rep"""
        ada = User.objects.create_user("ada@example.com", full_name="Ada")
        bob = User.objects.create_user("bob@example.com", full_name="Bob")
        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        kitchen.create_core_roles()
        bakery = Role.objects.create(name="Bakery", is_circle=True, circle=kitchen)
        bakery.create_core_roles()
        baker = Role.objects.create(name="Baker", circle=bakery)
        for core_role, user in [("lead", ada), ("rep", bob)]:
            Assignment.objects.create(
                role=bakery.roles.get(core_role=core_role), user=user
            )
            Assignment.objects.create(role=bakery, user=user)
        adopt(
            Proposal.objects.create(
                circle=bakery,
                proposer=ada,
                tension="Bread",
                status=Proposal.PUBLISHED,
                instructions=[{"op": "remove", "path": f"/roles/{baker.pk}"}],
                created_at=timezone.now(),
            )
        )
        bakery.refresh_from_db()
        self.assertFalse(bakery.is_circle)
        self.assertEqual(
            list(
                Assignment.objects
                .current()
                .filter(role=bakery)
                .values_list("user", flat=True)
            ),
            [ada.pk],
        )
