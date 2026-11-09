from django.core import mail
from django.test import TestCase
from django.utils import timezone

from governance.accounts.models import User
from governance.notifications.mails import recipients
from governance.proposals.models import Proposal, Response
from governance.proposals.process import (
    back_to_draft,
    draft_again,
    publish,
    respond,
    retract,
)
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

    def waiter(self, user):
        waiter = Role.objects.create(name="Waiter", circle=self.kitchen)
        Assignment.objects.create(role=waiter, user=user)
        return waiter

    def test_mails(self):
        proposal = Proposal.objects.create(
            circle=self.kitchen,
            proposer=self.eve,
            role=self.waiter(self.eve),
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

        # Withdrawn by its proposer: everybody learns where it went
        with self.captureOnCommitCallbacks(execute=True):
            publish(proposal)
        mail.outbox = []
        with self.captureOnCommitCallbacks(execute=True):
            retract(proposal)
        self.assertEqual(
            sorted(m.to[0] for m in mail.outbox),
            ["ada@example.com", "bob@example.com", "eve@example.com"],
        )
        self.assertIn("has withdrawn", mail.outbox[0].body)
        proposal = draft_again(proposal)

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

    def test_changes_in_the_recipients_language(self):
        """The changes are described in each recipient's language, not in
        the language of whoever caused the mail"""
        from django.utils.translation import override

        proposal = Proposal.objects.create(
            circle=self.kitchen,
            proposer=self.ada,
            role=self.cook,
            tension="Bread",
            created_at=timezone.now(),
            instructions=[
                {"op": "add", "path": "/roles/n1"},
                {"op": "add", "path": "/roles/n1/name", "value": "Baker"},
            ],
        )
        with override("en"), self.captureOnCommitCallbacks(execute=True):
            publish(proposal)
        to_bob = next(m for m in mail.outbox if m.to == ["bob@example.com"])
        self.assertIn("Rolle hinzugefügt", to_bob.body)

    def test_responses(self):
        """Questions go to the proposer, their answers to those who asked;
        requests for a meeting to the proposer and the Secretary, who
        prepares it. Consents stay silent."""
        secretary = self.kitchen.roles.create(name="Secretary", core_role="secretary")
        Assignment.objects.create(role=secretary, user=self.zoe)
        proposal = Proposal.objects.create(
            circle=self.kitchen,
            proposer=self.eve,
            role=self.waiter(self.eve),
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
        publish(proposal)

        def sent(user, kind, text=""):
            mail.outbox = []
            with self.captureOnCommitCallbacks(execute=True):
                respond(proposal, user, kind, text)
            return {m.to[0]: m for m in mail.outbox}

        to = sent(self.ada, Response.COMMENT, "Why Chef?")
        self.assertEqual(list(to), ["eve@example.com"])
        self.assertIn("Ada", to["eve@example.com"].body)
        self.assertIn("Why Chef?", to["eve@example.com"].body)
        self.assertIn(f"/proposals/{proposal.pk}/", to["eve@example.com"].body)

        # The proposer's answer goes to everybody who asked
        sent(self.bob, Response.COMMENT, "And when?")
        to = sent(self.eve, Response.COMMENT, "Shorter, and now.")
        self.assertEqual(sorted(to), ["ada@example.com", "bob@example.com"])
        self.assertIn("Shorter, and now.", to["ada@example.com"].body)
        self.assertIn("Antwort", to["bob@example.com"].subject)  # German
        # Not to those who left the circle meanwhile
        Assignment.objects.filter(user=self.bob).update(ends_on=timezone.localdate())
        to = sent(self.eve, Response.COMMENT, "Tomorrow.")
        self.assertEqual(sorted(to), ["ada@example.com"])
        Assignment.objects.filter(user=self.bob).update(ends_on=None)

        self.assertEqual(sent(self.ada, Response.CONSENT), {})

        to = sent(self.bob, Response.MEETING, "Too short")
        self.assertEqual(sorted(to), ["eve@example.com", "zoe@example.com"])
        self.assertIn("Too short", to["zoe@example.com"].body)
        # Why the Secretary gets it, not the proposer
        hint = "because you schedule the governance meetings of Kitchen"
        self.assertIn(hint, to["zoe@example.com"].body)
        self.assertNotIn(hint, to["eve@example.com"].body)

        # Without a Secretary the Facilitator stands in (constitution 5.3.6)
        Assignment.objects.filter(role=secretary).delete()
        facilitator = self.kitchen.roles.create(
            name="Facilitator", core_role="facilitator"
        )
        Assignment.objects.create(role=facilitator, user=self.zoe)
        proposal.pk = None
        proposal.status = Proposal.DRAFT
        proposal.save()
        publish(proposal)
        to = sent(self.bob, Response.MEETING, "Still too short")
        self.assertEqual(sorted(to), ["eve@example.com", "zoe@example.com"])

    def test_copies(self):
        """MAIL_COPIES get one copy of each mail, in the language of their
        account (if any), unless they received it themselves; as Cc without a To"""
        proposal = Proposal.objects.create(
            circle=self.kitchen,
            proposer=self.eve,
            role=self.waiter(self.eve),
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
        copies = ["Ada@example.com", "copy@example.com", "copy@example.com"]
        User.objects.create_user("zed@example.com", full_name="Zed", language="de")
        copies.append("Zed@example.com")
        with (
            self.settings(MAIL_COPIES=copies),
            self.captureOnCommitCallbacks(execute=True),
        ):
            publish(proposal)
        self.assertEqual(
            sorted((m.to, m.cc, m.subject) for m in mail.outbox),
            [
                ([], ["copy@example.com"], "Proposal in Kitchen: Better name"),
                ([], ["zed@example.com"], "Vorschlag in Kitchen: Better name"),
                (["ada@example.com"], [], "Proposal in Kitchen: Better name"),
                (["bob@example.com"], [], "Vorschlag in Kitchen: Better name"),
                (["eve@example.com"], [], "Proposal in Kitchen: Better name"),
            ],
        )

    def test_greeting(self):
        """Mails greet the recipient by their first name in their language
        and end with a link to the overview of the mails"""
        self.bob.full_name = "Bob Müller"
        self.bob.save()
        proposal = Proposal.objects.create(
            circle=self.kitchen,
            proposer=self.ada,
            role=self.cook,
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
        with (
            self.settings(MAIL_COPIES=["copy@example.com"]),
            self.captureOnCommitCallbacks(execute=True),
        ):
            publish(proposal)
        bodies = {(m.to or m.cc)[0]: m.body for m in mail.outbox}
        self.assertTrue(bodies["ada@example.com"].startswith("Hello Ada,\n\n"))
        self.assertTrue(bodies["bob@example.com"].startswith("Hallo Bob,\n\n"))
        # Copies say whose mail they are
        self.assertTrue(
            bodies["copy@example.com"].startswith(
                "Copy of the mail to Ada, Bob Müller.\n\nHello,\n\n"
            )
        )
        self.assertIn("/help/mails/", bodies["ada@example.com"])

    def test_setting(self):
        """Mails about everything, chosen in the settings"""
        self.client.force_login(self.zoe)
        response = self.client.get(f"/people/{self.zoe.pk}/")
        self.assertContains(response, "About the circles I'm a member of")
        self.client.post(
            "/accounts/settings/",
            {"full_name": "Zoe", "language": "en", "notify_all": "True"},
        )
        self.zoe.refresh_from_db()
        self.assertTrue(self.zoe.notify_all)
        self.assertContains(
            self.client.get(f"/people/{self.zoe.pk}/"),
            "About everything in all circles",
        )
        # Not on others' pages
        self.assertNotContains(self.client.get(f"/people/{self.ada.pk}/"), "Mails")


class AffectedTest(TestCase):
    def test_role_leads_of_removed_roles(self):
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

    def test_role_leads_since_today_of_roles_removed_in_a_meeting(self):
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

    def test_moved_into_a_sub_circle(self):
        """The Secretary of the circle a role moves into invites it to its
        meetings, its Circle Leads want to know; not its other members"""
        from governance.meetings.activity import end_meeting
        from governance.meetings.models import Meeting
        from governance.proposals.instructions import adopt

        ada, eve, sam, lou, hal = (
            User.objects.create_user(f"{name}@example.com", full_name=name)
            for name in ["ada", "eve", "sam", "lou", "hal"]
        )
        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        kitchen.create_core_roles()
        cook = Role.objects.create(name="Cook", circle=kitchen)
        Assignment.objects.create(role=cook, user=ada)
        bakery = Role.objects.create(name="Bakery", circle=kitchen, is_circle=True)
        bakery.create_core_roles()
        Role.objects.create(name="Baker", circle=bakery)
        oven = Role.objects.create(name="Oven", circle=bakery, is_circle=True)
        oven.create_core_roles()
        Assignment.objects.create(role=oven.roles.get(core_role="secretary"), user=sam)
        Assignment.objects.create(role=oven.roles.get(core_role="lead"), user=lou)
        Assignment.objects.create(
            role=Role.objects.create(name="Heater", circle=oven), user=hal
        )
        dishwasher = Role.objects.create(name="Dishwasher", circle=kitchen)
        Assignment.objects.create(role=dishwasher, user=eve)

        def move(role, meeting=None):
            return Proposal.objects.create(
                circle=kitchen,
                proposer=ada,
                tension="Ovens",
                created_at=timezone.now(),
                meeting=meeting,
                instructions=[
                    {
                        "op": "move",
                        "path": f"/roles/{oven.pk}/supporting_circle/roles/{role.pk}",
                    }
                ],
            )

        expected = [
            "ada@example.com",
            "eve@example.com",
            "lou@example.com",
            "sam@example.com",
        ]
        with self.captureOnCommitCallbacks(execute=True):
            adopt(move(cook))
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), expected)

        mail.outbox = []
        meeting = Meeting.objects.create(
            circle=kitchen, kind=Meeting.GOVERNANCE, started_at=timezone.now()
        )
        meeting.attendees.set([ada])
        with self.captureOnCommitCallbacks(execute=True):
            adopt(move(dishwasher, meeting))
            end_meeting(meeting)
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), expected)

    def test_moved_out_of_a_sub_circle(self):
        """Like moving into it: the sub-circle's Secretary and Circle Leads
        hear about it"""
        from governance.proposals.instructions import adopt

        ada, sam, lou, hal = (
            User.objects.create_user(f"{name}@example.com", full_name=name)
            for name in ["ada", "sam", "lou", "hal"]
        )
        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        kitchen.create_core_roles()
        Assignment.objects.create(
            role=Role.objects.create(name="Cook", circle=kitchen), user=ada
        )
        bakery = Role.objects.create(name="Bakery", circle=kitchen, is_circle=True)
        bakery.create_core_roles()
        Assignment.objects.create(
            role=bakery.roles.get(core_role="secretary"), user=sam
        )
        Assignment.objects.create(role=bakery.roles.get(core_role="lead"), user=lou)
        Role.objects.create(name="Baker", circle=bakery)
        oven = Role.objects.create(name="Oven", circle=bakery)
        Assignment.objects.create(role=oven, user=hal)
        with self.captureOnCommitCallbacks(execute=True):
            adopt(
                Proposal.objects.create(
                    circle=kitchen,
                    proposer=ada,
                    tension="Ovens",
                    created_at=timezone.now(),
                    instructions=[
                        {
                            "op": "move",
                            "path": f"/roles/{oven.pk}",
                            "from": f"/circles/{bakery.pk}/roles/{oven.pk}",
                        }
                    ],
                )
            )
        self.assertEqual(
            sorted(m.to[0] for m in mail.outbox),
            [
                "ada@example.com",
                "hal@example.com",
                "lou@example.com",
                "sam@example.com",
            ],
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
