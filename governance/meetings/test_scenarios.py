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
from governance.meetings.models import AgendaItem, Meeting
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
        self.client.force_login(self.ada)  # The facilitator
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
        # the roles removed with the bakery lose their holders with them
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
        self.client.force_login(self.ada)
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
            self.client.force_login(self.ada)
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
        """The bakery's meeting removes its last role: the bakery turns back
        into a role, its meeting ends with the proposal adopted, its other
        proposals are withdrawn, the attendees get the outputs"""
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

        self.client.force_login(ada)
        self.client.post(f"/roles/{bakery.pk}/meetings/new/")
        meeting = Meeting.objects.running().get()
        self.client.post(f"/meetings/{meeting.pk}/agenda/add/", {"label": "Bread"})
        item = AgendaItem.objects.get(meeting=meeting)
        self.client.post(f"/agenda/{item.pk}/process/")
        self.client.force_login(bob)
        self.client.post(f"/agenda/{item.pk}/proposal/")
        item.refresh_from_db()
        self.client.post(f"/proposals/{item.proposal.pk}/roles/{baker.pk}/remove/")
        self.client.force_login(ada)
        response = self.client.get(meeting.get_absolute_url())
        self.assertContains(response, "Bakery loses its last roles")
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(f"/agenda/{item.pk}/adopt/", follow=True)
        self.assertContains(response, "The proposal is adopted.")

        for obj in [bakery, meeting, item, item.proposal, other]:
            obj.refresh_from_db()
        self.assertFalse(bakery.is_circle)
        self.assertEqual(
            (item.proposal.status, item.is_completed), (Proposal.ADOPTED, True)
        )
        self.assertIsNotNone(meeting.ended_at)
        self.assertEqual(other.status, Proposal.WITHDRAWN)
        outputs = [m for m in mail.outbox if "Bread" in m.body]
        self.assertEqual(
            sorted(m.to[0] for m in outputs), ["ada@example.com", "bob@example.com"]
        )
