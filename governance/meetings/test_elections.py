import datetime as dt

import time_machine
from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from governance.accounts.models import User
from governance.meetings.elections import due_elections
from governance.meetings.models import Election, Meeting
from governance.roles.models import Assignment, Role


# A Monday
@time_machine.travel(dt.datetime(2026, 12, 7, 9, tzinfo=dt.UTC), tick=False)
class ElectionsTest(TestCase):
    def setUp(self):
        self.ada = User.objects.create_user("ada@example.com", full_name="Ada")
        self.bob = User.objects.create_user("bob@example.com", full_name="Bob")
        self.anchor = Role.objects.create(name="Example Ltd", is_circle=True)
        self.anchor.create_core_roles()
        self.kitchen = Role.objects.create(
            name="Kitchen", is_circle=True, circle=self.anchor
        )
        self.kitchen.create_core_roles()
        self.secretary = self.kitchen.roles.get(core_role="secretary")
        self.facilitator = self.kitchen.roles.get(core_role="facilitator")
        self.rep = self.kitchen.roles.get(core_role="rep")
        Assignment.objects.create(
            role=self.secretary,
            user=self.ada,
            starts_on=dt.date(2026, 1, 1),
            elected_until=dt.date(2026, 12, 20),
        )
        Assignment.objects.create(
            role=self.facilitator,
            user=self.bob,
            starts_on=dt.date(2026, 1, 1),
            elected_until=dt.date(2027, 6, 1),
        )
        self.meeting = Meeting.objects.create(
            circle=self.kitchen,
            kind=Meeting.GOVERNANCE,
            started_at=timezone.now(),
            secretary=self.ada,
        )

    def test_due_and_reminders(self):
        self.assertEqual(
            [(role, a and a.user) for role, a in due_elections([self.kitchen])],
            [(self.secretary, self.ada), (self.rep, None)],
        )
        self.client.force_login(self.ada)
        response = self.client.get(f"/roles/{self.kitchen.pk}/")
        self.assertContains(response, "Elections due")
        self.assertContains(response, "nobody elected")
        response = self.client.get(f"/people/{self.ada.pk}/")
        self.assertContains(response, "Elections due")

        call_command("fairy_tasks")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["ada@example.com"])
        self.assertIn("Circle Rep (Kitchen): nobody elected", mail.outbox[0].body)

    def test_record(self):
        self.client.force_login(self.ada)
        response = self.client.get(self.meeting.get_absolute_url())
        self.assertContains(response, "Record the election")
        url = f"/meetings/{self.meeting.pk}/elections/"
        # Re-elected: the term changes
        self.client.post(
            url,
            {
                "role": self.secretary.pk,
                "user": self.ada.pk,
                "term_ends_on": "2027-12-31",
            },
        )
        assignment = Assignment.objects.current().get(role=self.secretary)
        self.assertEqual(
            (assignment.user, assignment.elected_until),
            (self.ada, dt.date(2027, 12, 31)),
        )
        # Another person: the previous one's term ends
        self.client.post(
            url,
            {
                "role": self.facilitator.pk,
                "user": self.ada.pk,
                "term_ends_on": "2027-12-31",
            },
        )
        self.assertEqual(
            Assignment.objects.current().get(role=self.facilitator).user, self.ada
        )
        self.assertEqual(
            Assignment.objects.get(role=self.facilitator, user=self.bob).ends_on,
            dt.date(2026, 12, 7),
        )
        # Only members may be elected (Bob holds no role in the circle now)
        eve = User.objects.create_user("eve@example.com", full_name="Eve")
        response = self.client.post(
            url,
            {"role": self.rep.pk, "user": eve.pk, "term_ends_on": "2027-12-31"},
            follow=True,
        )
        self.assertContains(response, "Select a valid choice")
        # The Circle Lead can't be the Circle Rep
        lead = self.kitchen.roles.get(core_role="lead")
        Assignment.objects.create(role=lead, user=eve)
        response = self.client.post(
            url,
            {"role": self.rep.pk, "user": eve.pk, "term_ends_on": "2027-12-31"},
            follow=True,
        )
        self.assertContains(response, "A Circle Lead can&#x27;t be the Circle Rep.")
        Assignment.objects.create(
            role=Role.objects.create(name="Cook", circle=self.kitchen), user=self.bob
        )
        # The Circle Rep also holds the circle's role in the super-circle
        self.client.post(
            url,
            {"role": self.rep.pk, "user": self.bob.pk, "term_ends_on": "2027-12-31"},
        )
        self.assertIn(
            self.bob,
            [a.user for a in Assignment.objects.current().filter(role=self.kitchen)],
        )
        self.assertEqual(Election.objects.count(), 3)
        self.assertContains(self.client.get(self.meeting.get_absolute_url()), "Bob")
        # Only elected roles
        response = self.client.post(
            url,
            {"role": lead.pk, "user": self.bob.pk, "term_ends_on": "2027-12-31"},
            follow=True,
        )
        self.assertContains(response, "Select a valid choice")

        outsider = User.objects.create_user("max@example.com", full_name="Max")
        self.client.force_login(outsider)  # Not a member of the circle
        self.assertEqual(self.client.post(url, {}).status_code, 403)

    def test_elected_by_policy(self):
        cook = Role.objects.create(name="Cook", circle=self.kitchen)
        self.assertFalse(cook.is_elected)
        self.client.force_login(self.ada)  # The kitchen's Secretary
        self.assertContains(self.client.get(f"/roles/{cook.pk}/"), "Settings")
        self.client.post(f"/roles/{cook.pk}/settings/", {"is_elected_by_policy": "on"})
        cook.refresh_from_db()
        self.assertTrue(cook.is_elected)
        self.assertContains(self.client.get(f"/roles/{cook.pk}/"), "elected by policy")
        # Elected now: an election, not the Circle Leads assign it (they
        # only end assignments, resigning)
        self.assertNotContains(
            self.client.get(f"/roles/{cook.pk}/assignments/"), "Assign somebody"
        )
        self.assertIn(cook, [role for role, _a in due_elections([self.kitchen])])
        self.client.post(
            f"/meetings/{self.meeting.pk}/elections/",
            {"role": cook.pk, "user": self.bob.pk, "term_ends_on": "2027-12-31"},
        )
        self.assertEqual(Assignment.objects.current().get(role=cook).user, self.bob)

        # The circle's own setting
        self.client.post(
            f"/roles/{self.kitchen.pk}/settings/", {"async_acceptance_days": "2"}
        )
        self.kitchen.refresh_from_db()
        self.assertEqual(self.kitchen.async_acceptance_days, 2)
        self.assertContains(self.client.get(f"/roles/{self.kitchen.pk}/"), "2 days")

        # Others don't, core roles have no settings
        self.assertEqual(
            self.client.get(f"/roles/{self.secretary.pk}/settings/").status_code, 403
        )
        self.client.force_login(self.bob)
        self.assertEqual(
            self.client.get(f"/roles/{cook.pk}/settings/").status_code, 403
        )


class ElectionsAndRestructuringTest(TestCase):
    def test_removed_and_reverted_circles(self):
        """Elections of circles removed or turned back into roles aren't due
        anymore; a role elected by policy keeps being elected where it
        moves"""
        from governance.notifications.mails import elections_due
        from governance.proposals.instructions import adopt
        from governance.proposals.models import Proposal

        ada = User.objects.create_user("ada@example.com", full_name="Ada")
        bob = User.objects.create_user("bob@example.com", full_name="Bob")
        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        kitchen.create_core_roles()
        today = timezone.localdate()
        for core_role in ["facilitator", "secretary"]:
            Assignment.objects.create(
                role=kitchen.roles.get(core_role=core_role),
                user=ada,
                elected_until=today + dt.timedelta(days=365),
            )
        bakery = Role.objects.create(name="Bakery", is_circle=True, circle=kitchen)
        bakery.create_core_roles()
        Role.objects.create(name="Baker", circle=bakery)
        Assignment.objects.create(
            role=bakery.roles.get(core_role="secretary"),
            user=bob,
            elected_until=today + dt.timedelta(days=10),
        )
        pastry = Role.objects.create(name="Pastry", is_circle=True, circle=kitchen)
        pastry.create_core_roles()
        taster = Role.objects.create(
            name="Taster", circle=pastry, is_elected_by_policy=True
        )
        circles = list(Role.objects.active().circles())
        self.assertIn(bakery, {role.circle for role, _a in due_elections(circles)})

        adopt(
            Proposal.objects.create(
                circle=kitchen,
                proposer=ada,
                tension="Smaller kitchen",
                created_at=timezone.now(),
                instructions=[
                    {"op": "remove", "path": f"/roles/{bakery.pk}"},
                    {
                        "op": "move",
                        "path": f"/roles/{taster.pk}",
                        "from": f"/circles/{pastry.pk}/roles/{taster.pk}",
                    },
                ],
            )
        )
        pastry.refresh_from_db()
        self.assertFalse(pastry.is_circle)
        circles = list(Role.objects.active().circles())
        self.assertEqual(
            [(role, a) for role, a in due_elections(circles)], [(taster, None)]
        )
        self.client.force_login(ada)
        self.assertContains(
            self.client.get(kitchen.get_absolute_url()), "Elections due"
        )

        elections_due()
        self.assertEqual([m.to for m in mail.outbox], [["ada@example.com"]])
        self.assertIn("Taster (Kitchen): nobody elected", mail.outbox[0].body)
