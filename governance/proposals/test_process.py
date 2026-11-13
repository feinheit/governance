import datetime as dt

import time_machine
from django.core.management import call_command
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from governance.accounts.models import User
from governance.proposals.instructions import ProposalError
from governance.proposals.models import Proposal, Response
from governance.proposals.process import (
    adopt_due_proposals,
    expire_waiting,
    publish,
    respond,
)
from governance.roles.models import Assignment, Role


NOW = dt.datetime(2026, 12, 1, 9, tzinfo=dt.UTC)


@time_machine.travel(NOW, tick=False)
class ProcessTest(TestCase):
    def setUp(self):
        self.ada = User.objects.create_user("ada@example.com", full_name="Ada")
        self.bob = User.objects.create_user("bob@example.com", full_name="Bob")
        self.eve = User.objects.create_user("eve@example.com", full_name="Eve")
        self.kitchen = Role.objects.create(
            name="Kitchen", is_circle=True, async_acceptance_days=2
        )
        self.kitchen.create_core_roles()
        self.cook = Role.objects.create(name="Cook", circle=self.kitchen)
        for user in [self.ada, self.bob]:
            Assignment.objects.create(role=self.cook, user=user)

    def proposal(self, **kwargs):
        kwargs.setdefault("role", self.cook)
        return Proposal.objects.create(
            circle=self.kitchen,
            proposer=self.ada,
            tension="Better name",
            created_at=timezone.now(),
            instructions=[
                {"op": "test", "path": f"/roles/{self.cook.pk}"},
                {
                    "op": "replace",
                    "path": f"/roles/{self.cook.pk}/name",
                    "original_value": "Cook",
                    "value": "Chef",
                },
            ],
            names={f"roles/{self.cook.pk}": "Cook"},
            **kwargs,
        )

    def test_adopted_twice_at_once(self):
        """Two requests (or a click and the hourly task) adopting the same
        proposal: the second one changes nothing"""
        from governance.proposals.instructions import adopt
        from governance.proposals.process import try_adopting

        proposal = self.proposal(status=Proposal.PUBLISHED)
        proposal.instructions = [
            {"op": "add", "path": "/roles/n1"},
            {"op": "add", "path": "/roles/n1/name", "value": "Baker"},
        ]
        proposal.save()
        first = Proposal.objects.get(pk=proposal.pk)
        second = Proposal.objects.get(pk=proposal.pk)  # Loaded before
        adopt(first)
        with self.assertRaises(ProposalError):
            adopt(second)
        self.assertFalse(try_adopting(Proposal.objects.get(pk=proposal.pk)))
        stale = Proposal.objects.get(pk=proposal.pk)
        stale.status = Proposal.PUBLISHED
        self.assertFalse(try_adopting(stale))
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.ADOPTED)
        self.assertEqual(Role.objects.filter(name="Baker").count(), 1)

    def test_publish_and_consent(self):
        proposal = self.proposal()
        self.client.force_login(self.ada)
        self.assertContains(
            self.client.get(proposal.get_absolute_url()), "Publish (async)"
        )
        self.client.post(f"/proposals/{proposal.pk}/publish/")
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.PUBLISHED)
        self.assertEqual(proposal.deadline, NOW + dt.timedelta(days=2))
        self.assertEqual(list(proposal.roles.all()), [self.cook])

        self.client.force_login(self.bob)
        response = self.client.get(proposal.get_absolute_url())
        self.assertContains(response, "0 of 1")
        self.assertContains(response, "Respond")
        # A question doesn't decide anything
        self.client.post(
            f"/proposals/{proposal.pk}/respond/", {"kind": "comment", "text": "Why?"}
        )
        self.client.post(f"/proposals/{proposal.pk}/respond/", {"kind": "comment"})
        self.assertEqual(Response.objects.count(), 1)  # Without text: an error
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.PUBLISHED)

        # Bob is the only other member, his consent adopts it
        self.client.post(f"/proposals/{proposal.pk}/respond/", {"kind": "consent"})
        proposal.refresh_from_db()
        self.cook.refresh_from_db()
        self.assertEqual((proposal.status, self.cook.name), (Proposal.ADOPTED, "Chef"))

        # Eve isn't a member
        self.client.force_login(self.eve)
        self.assertNotContains(self.client.get(proposal.get_absolute_url()), "Respond")
        self.assertEqual(
            self.client.post(
                f"/proposals/{proposal.pk}/respond/", {"kind": "consent"}
            ).status_code,
            403,
        )

    def test_own_proposal_and_anonymous_responses(self):
        Assignment.objects.create(role=self.cook, user=self.eve)
        proposal = publish(self.proposal())
        # The proposer doesn't respond, only answers questions
        for kind in [Response.CONSENT, Response.MEETING, Response.OBJECTION]:
            with self.assertRaises(ProposalError):
                respond(proposal, self.ada, kind, "Mine")
        self.client.force_login(self.ada)
        response = self.client.get(proposal.get_absolute_url())
        self.assertNotContains(response, 'value="consent"')
        self.assertContains(response, 'value="comment"')
        self.client.post(f"/proposals/{proposal.pk}/respond/", {"kind": "consent"})
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.PUBLISHED)

        # Who consented isn't shown, who asked is
        respond(proposal, self.bob, Response.CONSENT)
        respond(proposal, self.bob, Response.COMMENT, "Why Chef?")
        respond(proposal, self.ada, Response.COMMENT, "Shorter")
        self.client.force_login(self.eve)
        response = self.client.get(proposal.get_absolute_url())
        self.assertContains(response, "1 of 2")
        self.assertContains(response, "Why Chef?")
        self.assertContains(response, "Shorter")
        self.assertEqual(response.content.decode().count("Bob"), 1)  # The question
        self.assertNotContains(response, "Eve</span>")  # No list of members

    def test_counts_current_members(self):
        """Only the responses of current members count, not those of people
        who left the circle since ("2 of 1")"""
        from governance.proposals.process import response_summary

        carl = User.objects.create_user("carl@example.com", full_name="Carl")
        for user in [self.eve, carl]:
            Assignment.objects.create(role=self.cook, user=user)
        proposal = publish(self.proposal())
        respond(proposal, self.bob, Response.CONSENT)
        respond(proposal, self.eve, Response.CONSENT)
        Assignment.objects.filter(user__in=[self.bob, self.eve]).delete()
        summary = response_summary(proposal)
        self.assertEqual((summary["consents"], summary["others"]), (0, 1))

    def test_objection_and_meeting(self):
        proposal = publish(self.proposal())
        self.client.force_login(self.bob)
        # No objections async: they're raised and tested in the meeting
        with self.assertRaises(ProposalError):
            respond(proposal, self.bob, Response.OBJECTION, "Causes harm")
        self.assertNotContains(
            self.client.get(proposal.get_absolute_url()), 'value="objection"'
        )
        self.client.post(
            f"/proposals/{proposal.pk}/respond/",
            {"kind": "meeting", "text": "Causes harm"},
        )
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.IN_MEETING)
        self.assertContains(self.client.get(proposal.get_absolute_url()), "Causes harm")
        # In the meeting only questions and comments remain
        with self.assertRaises(ProposalError):
            respond(proposal, self.bob, Response.CONSENT)
        respond(proposal, self.bob, Response.COMMENT, "Let's talk")

        other = publish(self.proposal())
        respond(other, self.bob, Response.MEETING)
        other.refresh_from_db()
        self.assertEqual(other.status, Proposal.IN_MEETING)

        self.client.force_login(self.ada)
        self.client.post(f"/proposals/{other.pk}/withdraw/")
        other.refresh_from_db()
        self.assertEqual(other.status, Proposal.WITHDRAWN)

    def test_only_members_respond(self):
        """Only circle members request a meeting or consent (5.3), admins
        who aren't members neither"""
        proposal = publish(self.proposal())
        admin = User.objects.create_user("max@example.com", is_admin=True)
        self.client.force_login(admin)
        self.assertNotContains(
            self.client.get(proposal.get_absolute_url()), 'value="meeting"'
        )
        response = self.client.post(
            f"/proposals/{proposal.pk}/respond/", {"kind": "meeting"}
        )
        self.assertEqual(response.status_code, 403)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.PUBLISHED)

    def test_deadline(self):
        from django.core import mail

        proposal = publish(self.proposal())
        conflicting = self.proposal()
        conflicting.tension = "Another name"
        conflicting = publish(conflicting)
        self.assertEqual(adopt_due_proposals(), [])
        with time_machine.travel(NOW + dt.timedelta(days=2, minutes=1), tick=False):
            mail.outbox = []
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(adopt_due_proposals(), [proposal])
            # The other one conflicts now: it goes to the meeting, those who
            # got it learn why
            conflicting.refresh_from_db()
            self.assertEqual(conflicting.status, Proposal.IN_MEETING)
            messages = [m for m in mail.outbox if "Another name" in m.subject]
            self.assertIn("next governance meeting", messages[0].body)
            self.assertIn("has been changed", messages[0].body)
            self.assertEqual(
                {m.to[0] for m in messages}, {"ada@example.com", "bob@example.com"}
            )
            call_command("hourly_tasks")

    def test_without_a_deadline(self):
        """Without a period set by policy (the circle's or a super-circle's),
        a proposal is only adopted once everybody consented (5.3)"""
        from django.core import mail

        self.kitchen.async_acceptance_days = None
        self.kitchen.save()
        with self.captureOnCommitCallbacks(execute=True):
            proposal = publish(self.proposal())
        self.assertEqual((proposal.deadline, proposal.adopted_on), (None, None))
        self.assertIn("only adopted once everybody consented", mail.outbox[0].body)
        self.assertNotIn("nothing to do", mail.outbox[0].body)
        with time_machine.travel(NOW + dt.timedelta(days=365), tick=False):
            self.assertEqual(adopt_due_proposals(), [])
            respond(proposal, self.bob, Response.CONSENT)
            proposal.refresh_from_db()
            self.assertEqual(proposal.status, Proposal.ADOPTED)

    def test_cannot_publish(self):
        tension = Proposal.objects.create(
            circle=self.kitchen,
            proposer=self.ada,
            tension="Just a tension",
            created_at=timezone.now(),
        )
        with self.assertRaises(ProposalError):
            publish(tension)
        proposal = self.proposal()
        Role.objects.filter(pk=self.cook.pk).update(name="Cuisinier")
        self.client.force_login(self.ada)
        response = self.client.post(f"/proposals/{proposal.pk}/publish/", follow=True)
        self.assertContains(response, "has been changed since the proposal was drafted")
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.DRAFT)

    def test_not_adopted_async_after_leaving_the_process(self):
        """A due proposal brought into a meeting or taken back to its draft
        while the daily task runs isn't adopted async"""
        from governance.proposals.process import try_adopting

        for status in [Proposal.IN_MEETING, Proposal.DRAFT]:
            with self.subTest(status=status):
                proposal = self.proposal(status=Proposal.PUBLISHED)
                stale = Proposal.objects.get(pk=proposal.pk)  # Loaded before
                Proposal.objects.filter(pk=proposal.pk).update(status=status)
                self.assertFalse(try_adopting(stale))
                proposal.refresh_from_db()
                self.assertEqual(proposal.status, status)
                self.cook.refresh_from_db()
                self.assertEqual(self.cook.name, "Cook")

    def test_responding_too_late(self):
        """Responding to a proposal adopted or withdrawn meanwhile (an open
        page) tells so instead of failing"""
        proposal = self.proposal(status=Proposal.ADOPTED)
        self.client.force_login(self.bob)
        for kind in [Response.CONSENT, Response.COMMENT]:
            with self.subTest(kind=kind):
                response = self.client.post(
                    f"/proposals/{proposal.pk}/respond/",
                    {"kind": kind, "text": "Hm?"},
                    follow=True,
                )
                self.assertContains(
                    response, "The proposal isn&#x27;t open for responses anymore."
                )
        self.assertFalse(proposal.responses.exists())

    def test_response_form(self):
        """Nothing chosen beforehand; no objection takes no text, which is
        refused instead of dropped (the page shows the field only for the
        responses taking one)"""
        proposal = publish(self.proposal())
        self.client.force_login(self.bob)
        response = self.client.get(proposal.get_absolute_url())
        self.assertNotContains(response, "checked")
        self.assertContains(response, 'data-shown-for="kind=comment meeting"')
        url = f"/proposals/{proposal.pk}/respond/"
        response = self.client.post(url, {"text": "Hm"}, follow=True)
        self.assertContains(response, "This field is required.")
        response = self.client.post(
            url, {"kind": Response.CONSENT, "text": "Fine by me"}, follow=True
        )
        self.assertContains(
            response, "No objection takes no text: ask a question or request a meeting."
        )
        self.assertFalse(proposal.responses.exists())
        # The API too
        from governance.accounts.models import APIToken

        _token, secret = APIToken.create_for(user=self.bob, title="CLI", access="write")
        response = self.client.post(
            f"/api/proposals/{proposal.pk}/responses/",
            {"kind": Response.CONSENT, "text": "Fine by me"},
            content_type="application/json",
            headers={"authorization": f"Bearer {secret}"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(proposal.responses.exists())

    def test_proposer_without_the_role(self):
        """Publishing needs the proposer's role still (5.3.1), e.g. after
        their assignment ended since drafting"""
        proposal = self.proposal(role=self.cook)
        Assignment.objects.filter(user=self.ada).update(ends_on=timezone.localdate())
        with self.assertRaises(ProposalError) as raised:
            publish(proposal)
        self.assertEqual(
            raised.exception.problems,
            ["Ada doesn't hold Cook in Kitchen anymore: choose another role."],
        )
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.DRAFT)

        # Holding another role of the circle, the proposal comes from that one
        waiter = Role.objects.create(name="Waiter", circle=self.kitchen)
        Assignment.objects.create(role=waiter, user=self.ada)
        proposal.role = waiter
        proposal.save()
        publish(proposal)
        self.assertEqual(proposal.status, Proposal.PUBLISHED)

    def test_proposer_without_a_role(self):
        """A draft without a role (e.g. a guest's item of a meeting drafted
        again, a draft imported from GlassFrog) needs one to be published"""
        proposal = self.proposal(role=None)
        with self.assertRaises(ProposalError) as raised:
            publish(proposal)
        self.assertEqual(
            raised.exception.problems,
            ["Choose the role of the proposer the tension comes from."],
        )
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.DRAFT)

    def test_pending_and_person(self):
        draft = self.proposal()
        proposal = publish(self.proposal())
        self.client.force_login(self.bob)
        response = self.client.get(f"/roles/{self.cook.pk}/")
        self.assertContains(response, "Proposed")
        self.assertContains(response, proposal.get_absolute_url())
        self.assertContains(self.client.get(f"/roles/{self.kitchen.pk}/"), "Proposed")
        response = self.client.get(f"/people/{self.bob.pk}/")
        self.assertContains(response, "Waiting for your response")
        respond(proposal, self.bob, Response.COMMENT, "Hm?")
        self.assertContains(
            self.client.get(f"/people/{self.bob.pk}/"), "Waiting for your response"
        )
        respond(proposal, self.bob, Response.MEETING)
        self.assertNotContains(
            self.client.get(f"/people/{self.bob.pk}/"), "Waiting for your response"
        )
        # Drafts only on the own page
        self.assertNotContains(
            self.client.get(f"/people/{self.ada.pk}/"), draft.get_absolute_url()
        )
        self.client.force_login(self.ada)
        self.assertContains(
            self.client.get(f"/people/{self.ada.pk}/"), draft.get_absolute_url()
        )

    def test_waiting_for_the_response(self):
        """The person page lists the proposals waiting for one's response:
        responses since publishing again count, and those of all circles
        one is a member of, also inside a role one holds"""
        from governance.proposals.process import back_to_draft

        Assignment.objects.create(role=self.cook, user=self.eve)
        proposal = publish(self.proposal())
        respond(proposal, self.bob, Response.CONSENT)
        back_to_draft(proposal)
        with time_machine.travel(NOW + dt.timedelta(hours=1), tick=False):
            publish(proposal)
        inside = publish(
            Proposal.objects.create(
                circle=self.cook,
                role=self.cook,
                proposer=self.ada,
                tension="Too much to do",
                created_at=timezone.now(),
                instructions=[
                    {"op": "add", "path": "/roles/n1"},
                    {"op": "add", "path": "/roles/n1/name", "value": "Dishes"},
                ],
            )
        )
        self.client.force_login(self.bob)
        response = self.client.get(f"/people/{self.bob.pk}/")
        self.assertEqual(list(response.context["waiting"]), [inside, proposal])

    def test_consequences_for_everybody(self):
        """Those responding see what adopting does automatically, not only
        the proposer"""
        bakery = Role.objects.create(name="Bakery", is_circle=True, circle=self.kitchen)
        bakery.create_core_roles()
        baker = Role.objects.create(name="Baker", circle=bakery)
        for user in [self.ada, self.bob]:
            Assignment.objects.create(role=baker, user=user)
        proposal = publish(
            Proposal.objects.create(
                circle=bakery,
                role=baker,
                proposer=self.ada,
                tension="No more bread",
                created_at=timezone.now(),
                instructions=[{"op": "remove", "path": f"/roles/{baker.pk}"}],
            )
        )
        self.client.force_login(self.bob)
        self.assertContains(
            self.client.get(proposal.get_absolute_url()),
            "Bakery loses its last roles",
        )

    def test_back_to_draft(self):
        """A published proposal is changed by taking it back to its draft"""
        proposal = publish(self.proposal())
        respond(proposal, self.bob, Response.COMMENT, "Why Chef?")
        self.client.force_login(self.ada)
        url = f"/proposals/{proposal.pk}/roles/{self.cook.pk}/"
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertContains(
            self.client.get(proposal.get_absolute_url()), "Back to the draft"
        )
        self.client.post(f"/proposals/{proposal.pk}/draft/")
        proposal.refresh_from_db()
        self.assertEqual(
            (proposal.status, proposal.published_at, proposal.deadline),
            (Proposal.DRAFT, None, None),
        )
        self.assertEqual(self.client.get(url).status_code, 200)
        # Others don't see it anymore, and it can't go back twice
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(proposal.get_absolute_url()).status_code, 404)

        # Published again: the earlier round doesn't count, Bob's consent does
        with time_machine.travel(NOW + dt.timedelta(hours=1), tick=False):
            publish(proposal)
            self.assertFalse(
                self.client
                .get(proposal.get_absolute_url())
                .content.decode()
                .count("Why Chef?")
            )
            respond(proposal, self.bob, Response.CONSENT)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.ADOPTED)


class ConcurrentAdoptionTest(TransactionTestCase):
    def test_one_after_the_other(self):
        """Two proposals adopted at once see each other's changes: the
        bakery's last role removed while the kitchen moves a role into it
        leaves a circle, not a role with roles inside"""
        import threading

        from django.db import connection, transaction

        from governance.proposals.instructions import adopt

        ada = User.objects.create_user("ada@example.com", full_name="Ada")
        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        kitchen.create_core_roles()
        bakery = Role.objects.create(name="Bakery", is_circle=True, circle=kitchen)
        bakery.create_core_roles()
        baker = Role.objects.create(name="Baker", circle=bakery)
        cook = Role.objects.create(name="Cook", circle=kitchen)

        def proposal(circle, instruction):
            return Proposal.objects.create(
                circle=circle,
                proposer=ada,
                tension="Bread",
                created_at=timezone.now(),
                instructions=[instruction],
            )

        remove = proposal(bakery, {"op": "remove", "path": f"/roles/{baker.pk}"})
        move = proposal(
            kitchen,
            {
                "op": "move",
                "path": f"/roles/{bakery.pk}/supporting_circle/roles/{cook.pk}",
                "from": f"/roles/{cook.pk}",
            },
        )
        adopted, done = threading.Event(), threading.Event()

        def first():
            with transaction.atomic():
                adopt(remove)
                adopted.set()
                done.wait(1)  # The other adopts meanwhile, or waits
            connection.close()

        def second():
            adopt(move)
            done.set()
            connection.close()

        threads = [threading.Thread(target=first), threading.Thread(target=second)]
        threads[0].start()
        adopted.wait(5)
        threads[1].start()
        for thread in threads:
            thread.join()
        bakery.refresh_from_db()
        cook.refresh_from_db()
        self.assertEqual((cook.circle, bakery.is_circle), (bakery, True))


@time_machine.travel(NOW, tick=False)
class WaitingTest(TestCase):
    """Proposals waiting for a meeting go back to their proposer's draft
    after three months (decided 2026-11-13)"""

    def setUp(self):
        self.ada = User.objects.create_user("ada@example.com", full_name="Ada")
        self.bob = User.objects.create_user("bob@example.com", full_name="Bob")
        self.kitchen = Role.objects.create(
            name="Kitchen", is_circle=True, async_acceptance_days=2
        )
        self.kitchen.create_core_roles()
        self.cook = Role.objects.create(name="Cook", circle=self.kitchen)
        for user in [self.ada, self.bob]:
            Assignment.objects.create(role=self.cook, user=user)

    def waiting(self):
        proposal = publish(
            Proposal.objects.create(
                circle=self.kitchen,
                proposer=self.ada,
                role=self.cook,
                tension="Better name",
                created_at=timezone.now(),
                instructions=[{"op": "test", "path": f"/roles/{self.cook.pk}"}],
            )
        )
        respond(proposal, self.bob, Response.MEETING)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.IN_MEETING)
        self.assertEqual(proposal.waiting_since, NOW)
        return proposal

    def test_back_to_the_draft(self):
        from django.core import mail

        proposal = self.waiting()
        with time_machine.travel(NOW + dt.timedelta(days=89), tick=False):
            self.assertEqual(expire_waiting(), [])
        with time_machine.travel(NOW + dt.timedelta(days=91), tick=False):
            mail.outbox = []
            with self.captureOnCommitCallbacks(execute=True):
                call_command("fairy_tasks")
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.DRAFT)
        self.assertEqual((proposal.published_at, proposal.waiting_since), (None, None))
        # Only the proposer, whose draft it is
        self.assertEqual([m.to for m in mail.outbox], [["ada@example.com"]])
        self.assertIn("waited three months", mail.outbox[0].body)

    def test_meetings(self):
        """Not while on a running meeting's agenda; the end of a meeting
        leaving it waiting restarts the period"""
        from governance.meetings.activity import end_meeting
        from governance.meetings.models import Meeting

        proposal = self.waiting()
        meeting = Meeting.objects.create(
            circle=self.kitchen, kind=Meeting.GOVERNANCE, started_at=NOW
        )
        Proposal.objects.filter(pk=proposal.pk).update(meeting=meeting)
        later = NOW + dt.timedelta(days=91)
        self.assertEqual(expire_waiting(now=later), [])
        end_meeting(meeting, at=NOW + dt.timedelta(days=30))
        self.assertEqual(expire_waiting(now=later), [])
        self.assertEqual(expire_waiting(now=later + dt.timedelta(days=30)), [proposal])

    def test_without_proposer(self):
        """Nobody would see the draft of somebody who left: withdrawn"""
        proposal = self.waiting()
        User.objects.filter(pk=self.ada.pk).update(is_active=False)
        self.assertEqual(expire_waiting(now=NOW + dt.timedelta(days=91)), [])
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.WITHDRAWN)
