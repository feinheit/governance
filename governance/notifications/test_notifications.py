from django.core import mail
from django.test import TestCase
from django.utils import timezone

from governance.accounts.models import User
from governance.notifications.mails import recipients
from governance.proposals.models import Proposal, Response
from governance.proposals.process import back_to_draft, publish, respond
from governance.roles.models import Assignment, Role


class NotificationsTest(TestCase):
    def setUp(self):
        self.ada = User.objects.create_user("ada@example.com", full_name="Ada")
        self.bob = User.objects.create_user(
            "bob@example.com", full_name="Bob", language="de"
        )
        self.eve = User.objects.create_user("eve@example.com", full_name="Eve")
        self.zoe = User.objects.create_user("zoe@example.com", full_name="Zoe")
        self.anchor = Role.objects.create(name="Example Ltd", is_circle=True)
        self.kitchen = Role.objects.create(
            name="Kitchen", is_circle=True, circle=self.anchor
        )
        self.cook = Role.objects.create(name="Cook", circle=self.kitchen)
        for user in [self.ada, self.bob]:
            Assignment.objects.create(role=self.cook, user=user)

    def test_recipients(self):
        """The members, and whoever wants to know everything"""
        self.assertEqual(set(recipients(self.kitchen)), {self.ada, self.bob})
        self.assertEqual(set(recipients(self.anchor)), set())
        self.zoe.notify_all = True
        self.zoe.save()
        self.assertEqual(set(recipients(self.kitchen)), {self.ada, self.bob, self.zoe})
        self.assertEqual(set(recipients(self.anchor)), {self.zoe})

    def test_mails(self):
        proposal = Proposal.objects.create(
            circle=self.kitchen,
            proposer=self.eve,  # E.g. an admin, not a member
            tension="Better name",
            created_at=timezone.now(),
            instructions=[
                {
                    "op": "replace",
                    "path": f"/roles/{self.cook.pk}/name",
                    "original_value": "Cook",
                    "value": "Chef",
                }
            ],
            names={f"roles/{self.cook.pk}": "Cook"},
        )
        with self.captureOnCommitCallbacks(execute=True):
            publish(proposal)
        self.assertEqual(
            sorted(m.to[0] for m in mail.outbox),
            ["ada@example.com", "bob@example.com", "eve@example.com"],
        )
        to_bob = next(m for m in mail.outbox if m.to == ["bob@example.com"])
        self.assertIn("Vorschlag in Kitchen: Better name", to_bob.subject)
        to_ada = next(m for m in mail.outbox if m.to == ["ada@example.com"])
        self.assertIn("- Cook\n  + Chef", to_ada.body)
        self.assertIn(f"/proposals/{proposal.pk}/", to_ada.body)

        mail.outbox = []
        with self.captureOnCommitCallbacks(execute=True):
            back_to_draft(proposal)
        self.assertEqual(len(mail.outbox), 3)
        self.assertIn("back to the draft", mail.outbox[0].body)

        mail.outbox = []
        with self.captureOnCommitCallbacks(execute=True):
            publish(proposal)
            respond(proposal, self.ada, Response.CONSENT)
            respond(proposal, self.bob, Response.CONSENT)
        # Bob reads German
        adopted = [
            m for m in mail.outbox if m.subject.startswith(("Adopted", "Angenommen"))
        ]
        self.assertEqual(
            sorted(m.to[0] for m in adopted),
            ["ada@example.com", "bob@example.com", "eve@example.com"],
        )

    def test_setting(self):
        self.client.force_login(self.zoe)
        response = self.client.get(f"/people/{self.zoe.pk}/")
        self.assertContains(response, "the circles you're a member of")
        self.client.post("/accounts/notifications/", {"notify_all": "1"})
        self.zoe.refresh_from_db()
        self.assertTrue(self.zoe.notify_all)
        self.assertContains(
            self.client.get(f"/people/{self.zoe.pk}/"), "everything in all circles"
        )
        # Not on others' pages
        self.assertNotContains(self.client.get(f"/people/{self.ada.pk}/"), "Mails")
        self.client.post("/accounts/notifications/", {"notify_all": "0"})
        self.zoe.refresh_from_db()
        self.assertFalse(self.zoe.notify_all)


class AffectedTest(TestCase):
    def test_holders_of_removed_roles(self):
        """Who loses a role with the proposal is told, though not a member
        anymore when the mail goes out"""
        from governance.proposals.instructions import adopt

        ada = User.objects.create_user("ada@example.com", full_name="Ada")
        eve = User.objects.create_user("eve@example.com", full_name="Eve")
        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        cook = Role.objects.create(name="Cook", circle=kitchen)
        dishwasher = Role.objects.create(name="Dishwasher", circle=kitchen)
        Assignment.objects.create(role=cook, user=ada)
        Assignment.objects.create(role=dishwasher, user=eve)
        proposal = Proposal.objects.create(
            circle=kitchen,
            proposer=ada,
            tension="Machines",
            created_at=timezone.now(),
            instructions=[{"op": "remove", "path": f"/roles/{dishwasher.pk}"}],
        )
        with self.captureOnCommitCallbacks(execute=True):
            adopt(proposal)
        self.assertEqual(
            sorted(m.to[0] for m in mail.outbox), ["ada@example.com", "eve@example.com"]
        )

    def test_holders_since_today_of_roles_removed_in_a_meeting(self):
        """Who got the role today and loses it in a meeting gets its outputs
        too, like adopting async"""
        from governance.meetings.activity import end_meeting
        from governance.meetings.models import Meeting
        from governance.proposals.instructions import adopt

        ada = User.objects.create_user("ada@example.com", full_name="Ada")
        eve = User.objects.create_user("eve@example.com", full_name="Eve")
        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        cook = Role.objects.create(name="Cook", circle=kitchen)
        dishwasher = Role.objects.create(name="Dishwasher", circle=kitchen)
        Assignment.objects.create(role=cook, user=ada)
        Assignment.objects.create(
            role=dishwasher, user=eve, starts_on=timezone.localdate()
        )
        meeting = Meeting.objects.create(
            circle=kitchen, kind=Meeting.GOVERNANCE, started_at=timezone.now()
        )
        meeting.attendees.set([ada])
        proposal = Proposal.objects.create(
            circle=kitchen,
            proposer=ada,
            tension="Machines",
            created_at=timezone.now(),
            meeting=meeting,
            instructions=[{"op": "remove", "path": f"/roles/{dishwasher.pk}"}],
        )
        with self.captureOnCommitCallbacks(execute=True):
            adopt(proposal)
            end_meeting(meeting)
        self.assertEqual(
            sorted(m.to[0] for m in mail.outbox), ["ada@example.com", "eve@example.com"]
        )

    def test_nothing_for_people_who_left(self):
        from governance.proposals.instructions import adopt

        ada = User.objects.create_user("ada@example.com", full_name="Ada")
        eve = User.objects.create_user(
            "eve@example.com", full_name="Eve", is_active=False
        )
        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        Assignment.objects.create(
            role=Role.objects.create(name="Cook", circle=kitchen), user=ada
        )
        proposal = Proposal.objects.create(
            circle=kitchen,
            proposer=eve,  # Published before she left
            tension="Soup",
            created_at=timezone.now(),
            instructions=[
                {"op": "add", "path": "/roles/n1"},
                {"op": "add", "path": "/roles/n1/name", "value": "Baker"},
            ],
        )
        with self.captureOnCommitCallbacks(execute=True):
            adopt(proposal)
        self.assertEqual([m.to[0] for m in mail.outbox], ["ada@example.com"])
