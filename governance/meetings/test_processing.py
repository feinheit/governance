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
            facilitator=self.ada,
            secretary=self.bob,
        )
        self.proposal = Proposal.objects.create(
            circle=self.kitchen,
            proposer=self.eve,
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
