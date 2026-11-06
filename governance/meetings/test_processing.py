import datetime as dt

from django.core import mail
from django.test import TestCase
from django.utils import timezone

from governance.accounts.models import User
from governance.meetings.models import AgendaItem, Meeting, Objection
from governance.proposals.models import Proposal
from governance.roles.models import Accountability, Assignment, Role


class ProcessingTest(TestCase):
    def setUp(self):
        self.ada = User.objects.create_user("ada@example.com", full_name="Ada")
        self.bob = User.objects.create_user("bob@example.com", full_name="Bob")
        self.eve = User.objects.create_user("eve@example.com", full_name="Eve")
        self.kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        self.kitchen.create_core_roles()
        self.cook = Role.objects.create(name="Cook", circle=self.kitchen)
        Assignment.objects.create(
            role=self.kitchen.roles.get(core_role="facilitator"), user=self.ada
        )
        Assignment.objects.create(
            role=self.kitchen.roles.get(core_role="secretary"), user=self.bob
        )
        Assignment.objects.create(role=self.cook, user=self.eve)
        self.meeting = Meeting.objects.create(
            circle=self.kitchen,
            kind=Meeting.GOVERNANCE,
            started_at=timezone.now(),
            secretary=self.bob,
        )
        self.proposal = Proposal.objects.create(
            circle=self.kitchen,
            proposer=self.eve,
            role=self.cook,
            tension="Better name",
            status=Proposal.IN_MEETING,
            meeting=self.meeting,
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
        self.item = AgendaItem.objects.create(
            meeting=self.meeting, proposal=self.proposal, label="Better name"
        )

    def test_proposal(self):
        self.client.force_login(self.ada)  # The facilitator
        self.client.post(f"/agenda/{self.item.pk}/process/")
        self.item.refresh_from_db()
        self.assertEqual(self.item.step, "present")
        response = self.client.get(self.meeting.get_absolute_url())
        self.assertContains(response, "Now")
        self.assertContains(response, "Chef")
        self.assertContains(response, "Clarifying questions")
        self.assertNotContains(response, "Propose changes")  # The secretary

        self.client.post(f"/agenda/{self.item.pk}/step/", {"step": "objections"})
        self.client.post(
            f"/agenda/{self.item.pk}/objections/",
            {"objector": f"{self.eve.pk}:{self.cook.pk}", "text": "Chefs are bossy"},
        )
        objection = Objection.objects.get()
        self.client.post(f"/agenda/{self.item.pk}/adopt/")
        self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.status, Proposal.IN_MEETING)  # Untested

        self.client.post(f"/objections/{objection.pk}/", {"action": "valid"})
        self.item.refresh_from_db()
        self.assertEqual(self.item.step, "integration")

        # The secretary amends the proposal
        self.client.force_login(self.bob)
        response = self.client.get(self.meeting.get_absolute_url())
        self.assertContains(response, "Propose changes")
        next_query = f"?next=%2Fmeetings%2F{self.meeting.pk}%2F"
        self.assertContains(
            response, f"/proposals/{self.proposal.pk}/roles/{self.cook.pk}/{next_query}"
        )
        # The form opens in the meeting's panel, "Cancel" leads back there
        response = self.client.get(
            f"/proposals/{self.proposal.pk}/roles/{self.cook.pk}/{next_query}"
        )
        self.assertContains(response, f'href="/meetings/{self.meeting.pk}/"')
        # Saving reloads the meeting's region (htmx), or the meeting
        response = self.client.post(
            f"/proposals/{self.proposal.pk}/roles/{self.cook.pk}/{next_query}",
            {"name": "Head chef", "purpose": ""},
            headers={"HX-Request": "true"},
        )
        self.assertIn(
            f'"path": "/meetings/{self.meeting.pk}/"', response["HX-Location"]
        )
        response = self.client.post(
            f"/proposals/{self.proposal.pk}/roles/{self.cook.pk}/{next_query}",
            {"name": "Head cook", "purpose": ""},
        )
        self.assertRedirects(response, self.meeting.get_absolute_url())
        # Not elsewhere
        response = self.client.post(
            f"/proposals/{self.proposal.pk}/roles/{self.cook.pk}/?next=https://example.com/",
            {"name": "Head cook", "purpose": ""},
        )
        self.assertRedirects(
            response, self.proposal.get_absolute_url(), fetch_redirect_response=False
        )
        self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.instructions[-1]["value"], "Head cook")
        self.assertEqual(
            self.client.post(f"/proposals/{self.proposal.pk}/delete/").status_code,
            403,
        )
        self.client.post(f"/objections/{objection.pk}/", {"action": "integrated"})
        self.client.post(f"/agenda/{self.item.pk}/adopt/")
        self.proposal.refresh_from_db()
        self.cook.refresh_from_db()
        self.meeting.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(
            (self.proposal.status, self.cook.name, self.item.is_completed),
            (Proposal.ADOPTED, "Head cook", True),
        )
        self.assertIsNone(self.meeting.current_item)

        # Non-members can't run it
        outsider = User.objects.create_user("max@example.com", full_name="Max")
        self.client.force_login(outsider)  # Not a member of the circle
        self.assertEqual(
            self.client.post(f"/agenda/{self.item.pk}/process/").status_code, 403
        )

    def test_no_governance_in_tactical_meetings(self):
        """Tactical meetings don't process proposals (5.4), also not through
        requests the page doesn't offer"""
        Meeting.objects.filter(pk=self.meeting.pk).update(ended_at=timezone.now())
        called = Meeting.objects.create(
            kind=Meeting.TACTICAL, started_at=timezone.now(), called_by=self.bob
        )
        regular = Meeting.objects.create(
            circle=self.kitchen,
            kind=Meeting.TACTICAL,
            started_at=timezone.now(),
            secretary=self.bob,
        )
        self.client.force_login(self.bob)
        for meeting in [regular, called]:
            item = AgendaItem.objects.create(meeting=meeting, label="Soup")
            for action in ["proposal", "adopt", "discard", "step", "objections"]:
                with self.subTest(meeting=meeting, action=action):
                    response = self.client.post(f"/agenda/{item.pk}/{action}/")
                    self.assertEqual(response.status_code, 403)
        self.assertFalse(Proposal.objects.exclude(pk=self.proposal.pk).exists())

    def test_outputs_end_with_the_meeting(self):
        """A proposal still waiting after the meeting and withdrawn later isn't
        one of its outputs"""
        from governance.meetings.activity import end_meeting
        from governance.meetings.outputs import meeting_outputs

        end_meeting(self.meeting)
        self.client.force_login(self.eve)
        self.client.post(f"/proposals/{self.proposal.pk}/withdraw/")
        self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.status, Proposal.WITHDRAWN)
        self.assertEqual(meeting_outputs(self.meeting)["withdrawn"], [])

    def test_only_open_proposals_with_changes_are_adopted(self):
        """A proposal withdrawn by its proposer meanwhile, or a tension
        without changes, isn't adopted in the meeting"""
        self.client.force_login(self.eve)
        # Asked first, e.g. in a modal
        self.assertContains(
            self.client.get(f"/proposals/{self.proposal.pk}/withdraw/"),
            "You can draft it again afterwards.",
        )
        self.client.post(f"/proposals/{self.proposal.pk}/withdraw/")
        self.client.force_login(self.ada)
        self.client.post(f"/agenda/{self.item.pk}/adopt/")
        self.proposal.refresh_from_db()
        self.cook.refresh_from_db()
        self.assertEqual(
            (self.proposal.status, self.cook.name), (Proposal.WITHDRAWN, "Cook")
        )

        tension = Proposal.objects.create(
            circle=self.kitchen,
            proposer=self.eve,
            tension="Noise",
            status=Proposal.IN_MEETING,
            meeting=self.meeting,
            created_at=timezone.now(),
        )
        item = AgendaItem.objects.create(meeting=self.meeting, proposal=tension)
        self.client.post(f"/agenda/{item.pk}/adopt/")
        tension.refresh_from_db()
        self.assertEqual(tension.status, Proposal.IN_MEETING)

    def test_proposals_come_from_roles(self):
        """A guest's tension becomes a proposal without a role, which isn't
        adopted (5.3.1), like a proposal from a role its proposer left"""
        guest = User.objects.create_user("max@example.com", full_name="Max")
        self.meeting.attendees.add(guest)
        self.client.force_login(guest)
        self.client.post(f"/meetings/{self.meeting.pk}/agenda/add/", {"label": "Tea"})
        item = AgendaItem.objects.get(label="Tea")
        self.client.force_login(self.bob)
        self.client.post(f"/agenda/{item.pk}/proposal/")
        item.refresh_from_db()
        proposal = item.proposal
        self.assertIsNone(proposal.role)
        proposal.instructions = [{"op": "add", "path": "/roles/n1"}]
        proposal.save()
        self.client.post(f"/agenda/{item.pk}/adopt/")
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.IN_MEETING)

        # Eve's proposal from her role, which she left meanwhile
        self.proposal.role = self.cook
        self.proposal.save()
        Assignment.objects.filter(user=self.eve).delete()
        self.client.post(f"/agenda/{self.item.pk}/adopt/")
        self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.status, Proposal.IN_MEETING)

    def test_removed_from_the_agenda(self):
        """A proposal removed from the agenda goes back where it was: a draft
        stays private, an async proposal keeps its deadline"""
        deadline = timezone.now() + dt.timedelta(days=2)
        draft = Proposal.objects.create(
            circle=self.kitchen,
            proposer=self.eve,
            role=self.cook,
            tension="Draft",
            created_at=timezone.now(),
        )
        published = Proposal.objects.create(
            circle=self.kitchen,
            proposer=self.eve,
            role=self.cook,
            tension="Async",
            status=Proposal.PUBLISHED,
            created_at=timezone.now(),
            published_at=timezone.now(),
            deadline=deadline,
        )
        self.item.delete()
        self.client.force_login(self.eve)
        url = f"/meetings/{self.meeting.pk}/agenda/add/"
        for proposal in [draft, published, self.proposal]:
            self.client.post(url, {"proposal": proposal.pk})
            proposal.refresh_from_db()
            self.assertEqual(proposal.status, Proposal.IN_MEETING)
            item = self.meeting.agenda_items.get(proposal=proposal)
            self.client.post(f"/agenda/{item.pk}/remove/")
        for proposal, status in [
            (draft, Proposal.DRAFT),
            (published, Proposal.PUBLISHED),
            # Waiting for a meeting before, it waits for the next one
            (self.proposal, Proposal.IN_MEETING),
        ]:
            proposal.refresh_from_db()
            self.assertEqual(proposal.status, status)
        self.assertEqual(published.deadline, deadline)
        self.assertIsNone(draft.meeting)

    def test_discard(self):
        """The meeting discards a proposal (5.3.1, 5.3.4): it's withdrawn and
        in the outputs, its proposer drafts it again"""
        self.client.force_login(self.ada)
        self.client.post(f"/agenda/{self.item.pk}/process/")
        self.assertContains(self.client.get(self.meeting.get_absolute_url()), "Discard")
        self.client.post(f"/agenda/{self.item.pk}/discard/")
        self.proposal.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(
            (self.proposal.status, self.item.is_completed), (Proposal.WITHDRAWN, True)
        )
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(f"/meetings/{self.meeting.pk}/end/")
        self.assertIn("Withdrawn: Better name", mail.outbox[0].body)

        self.client.force_login(self.eve)
        response = self.client.get(self.proposal.get_absolute_url())
        self.assertContains(response, "Draft again")
        response = self.client.post(f"/proposals/{self.proposal.pk}/draft-again/")
        draft = Proposal.objects.latest("pk")
        self.assertRedirects(response, draft.get_absolute_url())
        self.assertEqual(
            (draft.status, draft.tension, draft.instructions, draft.role),
            (
                Proposal.DRAFT,
                "Better name",
                self.proposal.instructions,
                self.cook,
            ),
        )
        self.client.force_login(self.ada)  # Only the proposer
        self.assertEqual(
            self.client.post(f"/proposals/{self.proposal.pk}/draft-again/").status_code,
            403,
        )

    def test_objection_left_open(self):
        """A meeting ends with an untested objection: the next meeting
        processing the proposal tests it"""
        self.client.force_login(self.ada)
        self.client.post(f"/agenda/{self.item.pk}/process/")
        self.client.post(
            f"/agenda/{self.item.pk}/objections/",
            {"objector": f"{self.eve.pk}:{self.cook.pk}", "text": "Chefs are bossy"},
        )
        objection = Objection.objects.get()
        self.client.post(f"/meetings/{self.meeting.pk}/end/")

        self.client.post(f"/roles/{self.kitchen.pk}/meetings/new/")
        meeting = Meeting.objects.running().get()
        self.client.post(
            f"/meetings/{meeting.pk}/agenda/add/", {"proposal": self.proposal.pk}
        )
        item = AgendaItem.objects.get(meeting=meeting)
        self.client.post(f"/agenda/{item.pk}/process/")
        response = self.client.post(
            f"/objections/{objection.pk}/", {"action": "invalid"}
        )
        self.assertRedirects(response, meeting.get_absolute_url())
        objection.refresh_from_db()
        self.assertFalse(objection.is_valid)
        self.assertIsNotNone(objection.is_valid)
        self.client.post(f"/agenda/{item.pk}/adopt/")
        self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.status, Proposal.ADOPTED)

    def test_tension(self):
        item = AgendaItem.objects.create(
            meeting=self.meeting, label="Noise", owner=self.eve, position=2
        )
        self.client.force_login(self.bob)
        self.client.post(f"/agenda/{item.pk}/process/")
        self.assertContains(
            self.client.get(self.meeting.get_absolute_url()), "Capture a proposal"
        )
        response = self.client.post(f"/agenda/{item.pk}/proposal/")
        item.refresh_from_db()
        proposal = item.proposal
        # The secretary amends it right in the meeting
        self.assertRedirects(response, self.meeting.get_absolute_url())
        self.assertEqual(
            (proposal.proposer, proposal.status, proposal.meeting, proposal.tension),
            (self.eve, Proposal.IN_MEETING, self.meeting, "Noise"),
        )
        self.assertContains(self.client.get(proposal.get_absolute_url()), "Add a role")

        self.client.post(f"/agenda/{item.pk}/complete/")
        item.refresh_from_db()
        self.assertTrue(item.is_completed)

        # A conflict found when adopting
        Role.objects.filter(pk=self.cook.pk).update(name="Cuisinier")
        self.client.post(f"/agenda/{self.item.pk}/process/")
        response = self.client.post(f"/agenda/{self.item.pk}/adopt/", follow=True)
        self.assertContains(response, "has been changed since")

    def test_same_role_twice(self):
        """A proposal adopted earlier in the meeting changed the role: the
        meeting shows the conflict before adopting, the role's form in the
        proposal shows the current texts, saving it once takes them over"""
        cooking = Accountability.objects.create(role=self.cook, text="Cooking")
        self.proposal.instructions.append({
            "op": "replace",
            "path": f"/roles/{self.cook.pk}/accountabilities/{cooking.pk}/description",
            "original_value": "Cooking",
            "value": "Cooking food",
        })
        self.proposal.save()
        second = Proposal.objects.create(
            circle=self.kitchen,
            proposer=self.eve,
            role=self.cook,
            tension="Clearer role",
            status=Proposal.IN_MEETING,
            meeting=self.meeting,
            created_at=timezone.now(),
            instructions=[
                {"op": "test", "path": f"/roles/{self.cook.pk}"},
                {
                    "op": "replace",
                    "path": f"/roles/{self.cook.pk}/name",
                    "original_value": "Cook",
                    "value": "Head cook",
                },
                {
                    "op": "replace",
                    "path": (
                        f"/roles/{self.cook.pk}/accountabilities/{cooking.pk}"
                        "/description"
                    ),
                    "original_value": "Cooking",
                    "value": "Cooking meals",
                },
            ],
            names={f"roles/{self.cook.pk}": "Cook"},
        )
        item = AgendaItem.objects.create(
            meeting=self.meeting, proposal=second, label="Clearer role", position=2
        )
        self.client.force_login(self.ada)  # The facilitator
        self.client.post(f"/agenda/{self.item.pk}/process/")
        self.client.post(f"/agenda/{self.item.pk}/adopt/")
        self.cook.refresh_from_db()
        self.assertEqual(self.cook.name, "Chef")

        self.client.post(f"/agenda/{item.pk}/process/")
        self.assertContains(
            self.client.get(self.meeting.get_absolute_url()),
            "Chef: name has been changed since the proposal was drafted.",
        )

        # The secretary merges both in the role's form and saves it
        self.client.force_login(self.bob)
        url = f"/proposals/{second.pk}/roles/{self.cook.pk}/"
        form = self.client.get(url).context["form"]
        self.assertEqual(form["name"].initial, "Head cook")
        self.assertIn("currently: Chef", form["name"].help_text)
        self.assertIn("name_merged", form.fields)
        name = f"accountabilities-{cooking.pk}"
        self.assertEqual(
            form[name].initial,
            "<<<<<<< currently\nCooking food\n=======\nCooking meals\n>>>>>>> proposal",
        )
        self.assertNotIn("purpose_merged", form.fields)
        data = {field.name: field.initial for field in form}
        del data["name_merged"]
        # Neither confirmed nor merged
        form = self.client.post(url, data).context["form"]
        self.assertEqual(set(form.errors), {"name_merged", name})
        data |= {"name_merged": "on", name: "Cooking food and meals"}
        self.client.post(url, data)
        self.assertNotContains(
            self.client.get(self.meeting.get_absolute_url()), "has been changed since"
        )
        self.client.post(f"/agenda/{item.pk}/adopt/")
        second.refresh_from_db()
        self.cook.refresh_from_db()
        self.assertEqual(second.status, Proposal.ADOPTED)
        self.assertEqual(self.cook.name, "Head cook")
        self.assertEqual(
            list(self.cook.accountabilities.values_list("text", flat=True)),
            ["Cooking food and meals"],
        )

    def test_outputs_mail(self):
        from django.core import mail

        from governance.meetings.elections import record_election

        self.client.force_login(self.bob)
        self.client.post(f"/agenda/{self.item.pk}/process/")
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(f"/agenda/{self.item.pk}/adopt/")
        self.assertEqual(mail.outbox, [])  # Not during the meeting
        record_election(
            self.meeting,
            self.kitchen.roles.get(core_role="facilitator"),
            self.eve,
            timezone.localdate(),
        )
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(f"/meetings/{self.meeting.pk}/end/")
        # Ada isn't a member anymore, Eve replaced her as Facilitator
        self.assertEqual(
            sorted(m.to[0] for m in mail.outbox),
            ["bob@example.com", "eve@example.com"],
        )
        body = mail.outbox[0].body
        self.assertIn("Adopted: Better name", body)
        self.assertIn("+ Chef", body)
        self.assertIn("Facilitator: Eve", body)

    def test_outputs_reach_holders_of_removed_roles(self):
        """Somebody absent whose role the meeting removes still gets the
        outputs, like when adopting async"""
        max_ = User.objects.create_user("max@example.com", full_name="Max")
        waiter = Role.objects.create(name="Waiter", circle=self.kitchen)
        Assignment.objects.create(
            role=waiter,
            user=max_,
            starts_on=timezone.localdate() - dt.timedelta(days=9),
        )
        self.meeting.attendees.set([self.ada, self.bob, self.eve])
        self.proposal.instructions = [{"op": "remove", "path": f"/roles/{waiter.pk}"}]
        self.proposal.save()
        self.client.force_login(self.bob)
        self.client.post(f"/agenda/{self.item.pk}/adopt/")
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(f"/meetings/{self.meeting.pk}/end/")
        self.assertIn("max@example.com", [m.to[0] for m in mail.outbox])

    def test_async_concerns(self):
        """Concerns from requesting a meeting are context, objections are
        raised in the meeting"""
        from governance.proposals.models import Response

        self.proposal.status = Proposal.PUBLISHED
        self.proposal.published_at = timezone.now()
        self.proposal.save()
        Response.objects.create(
            proposal=self.proposal, user=self.eve, kind="meeting", text="Too bossy"
        )
        self.proposal.status = Proposal.IN_MEETING
        self.proposal.save()

        self.client.force_login(self.bob)
        self.client.post(f"/agenda/{self.item.pk}/process/")
        self.assertFalse(Objection.objects.exists())
        response = self.client.get(self.meeting.get_absolute_url())
        self.assertContains(response, "Concerns from the async process")
        self.assertContains(response, "Too bossy")
        self.assertContains(response, f"{self.eve.pk}:{self.cook.pk}")  # Eve – Cook

        # Only for a role the objector represents
        self.client.post(
            f"/agenda/{self.item.pk}/objections/",
            {"objector": f"{self.eve.pk}:{self.kitchen.pk}", "text": "No"},
        )
        self.assertFalse(Objection.objects.exists())
        self.client.post(
            f"/agenda/{self.item.pk}/objections/",
            {"objector": f"{self.eve.pk}:{self.cook.pk}", "text": "Too bossy"},
        )
        self.assertEqual(Objection.objects.get().role, self.cook)
