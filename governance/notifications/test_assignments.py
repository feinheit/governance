import datetime as dt

import time_machine
from django.core import mail
from django.test import TestCase
from django.utils import timezone

from governance.accounts.models import User
from governance.meetings.activity import end_meeting
from governance.meetings.elections import record_election
from governance.meetings.models import Meeting
from governance.roles.assignments import end_assignments_of
from governance.roles.models import Assignment, Role


@time_machine.travel(dt.datetime(2026, 12, 1, 12), tick=False)
class AssignmentMailsTest(TestCase):
    """People hear about roles they get and lose, the circle's Secretaries
    about people joining and leaving the circle (like GlassFrog)"""

    def setUp(self):
        self.ada = User.objects.create_user("ada@example.com", full_name="Ada")
        self.bob = User.objects.create_user("bob@example.com", full_name="Bob")
        self.eve = User.objects.create_user("eve@example.com", full_name="Eve")
        self.kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        self.kitchen.create_core_roles()
        self.cook = Role.objects.create(name="Cook", circle=self.kitchen)
        self.waiter = Role.objects.create(name="Waiter", circle=self.kitchen)
        started = dt.date(2026, 1, 1)
        Assignment.objects.create(
            role=self.kitchen.roles.get(core_role="lead"),
            user=self.ada,
            starts_on=started,
        )
        Assignment.objects.create(
            role=self.kitchen.roles.get(core_role="secretary"),
            user=self.bob,
            starts_on=started,
        )

    def outbox(self):
        sent = sorted((m.to[0], m.subject) for m in mail.outbox)
        mail.outbox = []
        return sent

    def test_assigning_and_removing(self):
        self.client.force_login(self.ada)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                f"/roles/{self.cook.pk}/assignments/", {"user": self.eve.pk}
            )
        to_secretary = next(m for m in mail.outbox if m.to == ["bob@example.com"])
        self.assertIn("as Secretary you invite the members", to_secretary.body)
        self.assertIn("Changed by Ada.", to_secretary.body)
        to_eve = next(m for m in mail.outbox if m.to == ["eve@example.com"])
        self.assertIn("Ada assigned you the role Cook in Kitchen.", to_eve.body)
        self.assertEqual(
            self.outbox(),
            [
                ("bob@example.com", "Members of Kitchen: Eve joined"),
                ("eve@example.com", "Your roles: Cook (Kitchen)"),
            ],
        )
        # Another role in the same circle: no change of members
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                f"/roles/{self.waiter.pk}/assignments/", {"user": self.eve.pk}
            )
        self.assertEqual(
            self.outbox(), [("eve@example.com", "Your roles: Waiter (Kitchen)")]
        )
        Assignment.objects.update(starts_on=dt.date(2026, 6, 1))
        for role in [self.cook, self.waiter]:
            assignment = Assignment.objects.get(role=role, user=self.eve)
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(f"/assignments/{assignment.pk}/end/")
        to_eve = next(m for m in mail.outbox if m.to == ["eve@example.com"])
        self.assertIn("Ada removed you from the role Cook in Kitchen.", to_eve.body)
        self.assertEqual(
            self.outbox(),
            [
                ("bob@example.com", "Members of Kitchen: Eve left"),
                ("eve@example.com", "Your roles: no longer Cook (Kitchen)"),
                ("eve@example.com", "Your roles: no longer Waiter (Kitchen)"),
            ],
        )

    def test_focus(self):
        """The Role Lead hears about their focus changing, nobody else"""
        assignment = Assignment.objects.create(
            role=self.cook, user=self.eve, focus="Soup"
        )
        self.client.force_login(self.ada)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                f"/assignments/{assignment.pk}/",
                {"user": self.eve.pk, "focus": "Salad"},
            )
        [message] = mail.outbox
        self.assertEqual(
            (message.to, message.subject),
            (["eve@example.com"], "Your focus in Cook (Kitchen): Salad"),
        )
        self.assertIn("Before: Soup", message.body)
        self.assertIn("Changed by Ada.", message.body)
        self.assertIn(f"/roles/{self.cook.pk}/", message.body)
        mail.outbox = []
        # Saved unchanged: nothing
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                f"/assignments/{assignment.pk}/",
                {"user": self.eve.pk, "focus": "Salad"},
            )
        self.assertEqual(self.outbox(), [])
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(f"/assignments/{assignment.pk}/", {"user": self.eve.pk})
        self.assertEqual(
            self.outbox(),
            [("eve@example.com", "Your focus in Cook (Kitchen) was removed")],
        )

    def test_focus_when_assigned(self):
        """The mail about the new role says the focus it starts with"""
        self.client.force_login(self.ada)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                f"/roles/{self.cook.pk}/assignments/",
                {"user": self.eve.pk, "focus": "Soup"},
            )
        [message] = [m for m in mail.outbox if m.to == ["eve@example.com"]]
        self.assertIn(
            "Ada assigned you the role Cook in Kitchen.\nFocus: Soup\n", message.body
        )

    def test_own_roles(self):
        """Changing one's own roles names nobody"""
        self.client.force_login(self.ada)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                f"/roles/{self.cook.pk}/assignments/", {"user": self.ada.pk}
            )
        [message] = [m for m in mail.outbox if m.to == ["ada@example.com"]]
        self.assertIn("You now hold Cook in Kitchen.", message.body)

    def test_sub_circles_following_the_circle_leads(self):
        """A sub-circle nobody leads follows the Circle Leads of the circle
        above (1.4.2): its Secretary hears about a new one"""
        bakery = Role.objects.create(name="Bakery", is_circle=True, circle=self.kitchen)
        bakery.create_core_roles()
        Role.objects.create(name="Baker", circle=bakery)
        Assignment.objects.create(
            role=bakery.roles.get(core_role="secretary"), user=self.eve
        )
        admin = User.objects.create_user("max@example.com", is_admin=True)
        self.client.force_login(admin)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                f"/roles/{self.kitchen.roles.get(core_role='lead').pk}/assignments/",
                {"user": self.bob.pk},
            )
        self.assertIn(
            ("eve@example.com", "Members of Bakery: Bob joined"), self.outbox()
        )

    def test_election(self):
        facilitator = self.kitchen.roles.get(core_role="facilitator")
        meeting = Meeting.objects.create(
            circle=self.kitchen, kind=Meeting.GOVERNANCE, started_at=timezone.now()
        )
        with self.captureOnCommitCallbacks(execute=True):
            record_election(meeting, facilitator, self.eve, dt.date(2027, 12, 1))
        self.assertEqual(self.outbox(), [])  # When the meeting ends
        with self.captureOnCommitCallbacks(execute=True):
            end_meeting(meeting)
        self.assertEqual(
            [m for m in self.outbox() if not m[1].startswith("Outputs")],
            [
                ("bob@example.com", "Members of Kitchen: Eve joined"),
                ("eve@example.com", "Your roles: Facilitator (Kitchen)"),
            ],
        )

    def test_deactivated_people_get_nothing(self):
        Assignment.objects.create(
            role=self.cook, user=self.eve, starts_on=dt.date(2026, 1, 1)
        )
        self.eve.is_active = False
        self.eve.save()
        with self.captureOnCommitCallbacks(execute=True):
            end_assignments_of(self.eve, timezone.localdate())
        self.assertEqual(
            self.outbox(), [("bob@example.com", "Members of Kitchen: Eve left")]
        )


class AdoptedMailsTest(TestCase):
    """People losing roles through an adopted proposal hear about it, also
    deeper inside: roles of a removed circle, the core roles of a circle
    turned back into a role"""

    def setUp(self):
        self.ada = User.objects.create_user("ada@example.com", full_name="Ada")
        self.bob = User.objects.create_user("bob@example.com", full_name="Bob")
        self.eve = User.objects.create_user("eve@example.com", full_name="Eve")
        self.kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        self.kitchen.create_core_roles()
        Assignment.objects.create(
            role=Role.objects.create(name="Cook", circle=self.kitchen), user=self.ada
        )
        self.bakery = Role.objects.create(
            name="Bakery", is_circle=True, circle=self.kitchen
        )
        self.bakery.create_core_roles()
        self.baker = Role.objects.create(name="Baker", circle=self.bakery)
        started = dt.date(2026, 1, 1)
        Assignment.objects.create(role=self.baker, user=self.bob, starts_on=started)
        Assignment.objects.create(
            role=self.bakery.roles.get(core_role="facilitator"),
            user=self.eve,
            starts_on=started,
        )

    def proposal(self, instructions, **kwargs):
        from governance.proposals.models import Proposal

        return Proposal.objects.create(
            circle=self.kitchen,
            proposer=self.ada,
            tension="Smaller",
            created_at=timezone.now(),
            instructions=instructions,
            **kwargs,
        )

    def test_async(self):
        from governance.proposals.instructions import adopt

        with self.captureOnCommitCallbacks(execute=True):
            adopt(self.proposal([{"op": "remove", "path": f"/roles/{self.bakery.pk}"}]))
        self.assertEqual(
            sorted(m.to[0] for m in mail.outbox),
            ["ada@example.com", "bob@example.com", "eve@example.com"],
        )

    def test_turned_back_from_above(self):
        from governance.proposals.instructions import adopt

        with self.captureOnCommitCallbacks(execute=True):
            adopt(
                self.proposal([
                    {
                        "op": "move",
                        "from": f"/circles/{self.bakery.pk}/roles/{self.baker.pk}",
                        "path": f"/roles/{self.baker.pk}",
                    }
                ])
            )
        self.assertIn("eve@example.com", [m.to[0] for m in mail.outbox])

    def test_turned_back_from_above_at_its_meetings_end(self):
        """The circle's own meeting ran: it turns back when the meeting ends,
        the super-circle's mail went out before"""
        from governance.meetings.activity import end_meeting
        from governance.proposals.instructions import adopt

        meeting = Meeting.objects.create(
            circle=self.bakery, kind=Meeting.TACTICAL, started_at=timezone.now()
        )
        with self.captureOnCommitCallbacks(execute=True):
            adopt(
                self.proposal([
                    {
                        "op": "move",
                        "from": f"/circles/{self.bakery.pk}/roles/{self.baker.pk}",
                        "path": f"/roles/{self.baker.pk}",
                    }
                ])
            )
        self.assertTrue(Assignment.objects.current().filter(user=self.eve).exists())
        mail.outbox = []
        with self.captureOnCommitCallbacks(execute=True):
            end_meeting(meeting)
        self.assertFalse(Assignment.objects.current().filter(user=self.eve).exists())
        self.assertEqual([m.to[0] for m in mail.outbox], ["eve@example.com"])

    def test_turned_back_while_the_super_circles_meeting_runs(self):
        """The super-circle's meeting empties the circle while both meetings
        run: those losing its core roles hear about it once, when the
        circle's meeting ends, not again from the super-circle's outputs"""
        from governance.meetings.activity import end_meeting
        from governance.proposals.instructions import adopt
        from governance.proposals.models import Proposal

        bakery_meeting = Meeting.objects.create(
            circle=self.bakery, kind=Meeting.TACTICAL, started_at=timezone.now()
        )
        kitchen_meeting = Meeting.objects.create(
            circle=self.kitchen, kind=Meeting.GOVERNANCE, started_at=timezone.now()
        )
        with self.captureOnCommitCallbacks(execute=True):
            adopt(
                self.proposal(
                    [
                        {
                            "op": "move",
                            "from": f"/circles/{self.bakery.pk}/roles/{self.baker.pk}",
                            "path": f"/roles/{self.baker.pk}",
                        }
                    ],
                    status=Proposal.IN_MEETING,
                    meeting=kitchen_meeting,
                )
            )
        with self.captureOnCommitCallbacks(execute=True):
            end_meeting(bakery_meeting)
        self.assertEqual([m.to[0] for m in mail.outbox], ["eve@example.com"])
        mail.outbox = []
        with self.captureOnCommitCallbacks(execute=True):
            end_meeting(kitchen_meeting)
        self.assertNotIn("eve@example.com", [m.to[0] for m in mail.outbox])

    def test_meeting(self):
        from governance.meetings.activity import end_meeting
        from governance.proposals.instructions import adopt
        from governance.proposals.models import Proposal

        meeting = Meeting.objects.create(
            circle=self.kitchen, kind=Meeting.GOVERNANCE, started_at=timezone.now()
        )
        meeting.attendees.set([self.ada])
        adopt(
            self.proposal(
                [{"op": "remove", "path": f"/roles/{self.bakery.pk}"}],
                status=Proposal.IN_MEETING,
                meeting=meeting,
            )
        )
        with self.captureOnCommitCallbacks(execute=True):
            end_meeting(meeting)
        self.assertEqual(
            sorted(m.to[0] for m in mail.outbox),
            ["ada@example.com", "bob@example.com", "eve@example.com"],
        )


class WithdrawnMailsTest(TestCase):
    def test_closing_a_circle_tells_its_proposers(self):
        """Removing a circle withdraws its open proposals, their proposers
        get a mail"""
        from governance.proposals.instructions import adopt
        from governance.proposals.models import Proposal

        ada = User.objects.create_user("ada@example.com", full_name="Ada")
        bob = User.objects.create_user("bob@example.com", full_name="Bob")
        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        kitchen.create_core_roles()
        bakery = Role.objects.create(name="Bakery", is_circle=True, circle=kitchen)
        bakery.create_core_roles()
        Role.objects.create(name="Baker", circle=bakery)
        Proposal.objects.create(
            circle=bakery,
            proposer=bob,
            tension="Ovens",
            status=Proposal.PUBLISHED,
            created_at=timezone.now(),
        )
        with self.captureOnCommitCallbacks(execute=True):
            adopt(
                Proposal.objects.create(
                    circle=kitchen,
                    proposer=ada,
                    tension="Smaller",
                    created_at=timezone.now(),
                    instructions=[{"op": "remove", "path": f"/roles/{bakery.pk}"}],
                )
            )
        withdrawn = [m for m in mail.outbox if m.subject.startswith("Withdrawn")]
        self.assertEqual(
            [(m.to[0], m.subject) for m in withdrawn],
            [("bob@example.com", "Withdrawn: Ovens")],
        )
        self.assertIn("Bakery has been removed", withdrawn[0].body)
