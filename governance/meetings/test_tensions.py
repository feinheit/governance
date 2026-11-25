import datetime as dt

from django.test import TestCase
from django.utils import timezone

from governance.accounts.models import User
from governance.meetings.models import AgendaItem, Meeting, Tension
from governance.proposals.models import Proposal
from governance.roles.models import Assignment, Role


class TensionInboxTest(TestCase):
    """The circles' tension inboxes (meetings/tensions.py)"""

    def setUp(self):
        self.ada = User.objects.create_user("ada@example.com", full_name="Ada")
        self.bob = User.objects.create_user("bob@example.com", full_name="Bob")
        self.eve = User.objects.create_user("eve@example.com", full_name="Eve")
        self.kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        self.kitchen.create_core_roles()
        self.cook = Role.objects.create(name="Cook", circle=self.kitchen)
        Assignment.objects.create(
            role=self.kitchen.roles.get(core_role="secretary"), user=self.ada
        )
        Assignment.objects.create(role=self.cook, user=self.bob)
        # Eve isn't a member of the kitchen
        self.sales = Role.objects.create(name="Sales", is_circle=True)
        self.sales.create_core_roles()
        Assignment.objects.create(
            role=self.sales.roles.get(core_role="secretary"), user=self.eve
        )

    def tension(self, owner, title, **kwargs):
        return Tension.objects.create(
            circle=self.kitchen, owner=owner, title=title, **kwargs
        )

    def start(self, kind="tactical"):
        self.client.force_login(self.ada)
        self.client.post(f"/roles/{self.kitchen.pk}/meetings/new/", {"kind": kind})
        return Meeting.objects.get(circle=self.kitchen, ended_at=None)

    def test_members_use_the_inbox(self):
        """The members see the inbox and add to it, others don't"""
        self.client.force_login(self.bob)
        response = self.client.post(
            f"/roles/{self.kitchen.pk}/tensions/new/",
            {"title": "Knives dull", "description": "Since **May**"},
        )
        self.assertRedirects(response, self.kitchen.get_absolute_url())
        tension = Tension.objects.get()
        self.assertEqual((tension.owner, tension.circle), (self.bob, self.kitchen))
        response = self.client.get(self.kitchen.get_absolute_url())
        self.assertContains(response, "Tension inbox")
        self.assertContains(response, "Knives dull")
        self.assertContains(response, "<strong>May</strong>", html=True)

        self.client.force_login(self.eve)
        self.assertNotContains(
            self.client.get(self.kitchen.get_absolute_url()), "Knives dull"
        )
        response = self.client.post(
            f"/roles/{self.kitchen.pk}/tensions/new/", {"title": "Mine"}
        )
        self.assertEqual(response.status_code, 403)

    def test_owner_changes_it(self):
        """Its owner edits and deletes it, the other members don't"""
        tension = self.tension(self.bob, "Knives dull")
        self.client.force_login(self.ada)
        for url in [f"/tensions/{tension.pk}/", f"/tensions/{tension.pk}/delete/"]:
            self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.bob)
        self.client.post(f"/tensions/{tension.pk}/", {"title": "Knives blunt"})
        tension.refresh_from_db()
        self.assertEqual(tension.title, "Knives blunt")
        self.client.post(f"/tensions/{tension.pk}/delete/")
        self.assertFalse(Tension.objects.exists())

    def test_private(self):
        """Private tensions are only their owner's, also in the meeting: the
        secretary doesn't see them, the owner adds them"""
        private = self.tension(self.bob, "Knives dull", is_private=True)
        self.client.force_login(self.ada)
        self.assertNotContains(
            self.client.get(self.kitchen.get_absolute_url()), "Knives dull"
        )
        meeting = self.start()
        url = f"/meetings/{meeting.pk}/agenda/tensions/"
        self.assertNotContains(self.client.get(url), "Knives dull")
        self.client.post(url, {"tensions": [private.pk]})
        self.assertFalse(meeting.agenda_items.exists())
        Assignment.objects.filter(user=self.bob).update(ends_on="2020-01-01")
        self.assertEqual(
            self.client.get(f"/tensions/{private.pk}/delete/").status_code, 403
        )
        Assignment.objects.filter(user=self.bob).update(ends_on=None)

        self.client.force_login(self.bob)
        self.assertContains(self.client.get(self.kitchen.get_absolute_url()), "private")
        self.assertContains(self.client.get(url), "Knives dull")
        self.client.post(url, {"tensions": [private.pk]})
        self.assertEqual(meeting.agenda_items.get().label, "Knives dull")

    def test_owner_left(self):
        """Once its owner isn't a member anymore the circle's acting
        Secretary deletes it, still not changes it"""
        tension = self.tension(self.bob, "Knives dull")
        self.client.force_login(self.ada)
        delete = f"/tensions/{tension.pk}/delete/"
        self.assertEqual(self.client.get(delete).status_code, 403)
        Assignment.objects.filter(user=self.bob).update(ends_on="2020-01-01")
        self.assertContains(self.client.get(self.kitchen.get_absolute_url()), delete)
        self.assertEqual(self.client.get(f"/tensions/{tension.pk}/").status_code, 403)
        self.client.post(delete)
        self.assertFalse(Tension.objects.exists())

    def test_older_collapsed(self):
        """The inbox shows the tensions' age, newest first, those older than
        three months collapsed"""
        self.tension(self.bob, "Knives dull")
        old = self.tension(self.bob, "Oven broken")
        Tension.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - dt.timedelta(days=100)
        )
        self.client.force_login(self.ada)
        response = self.client.get(self.kitchen.get_absolute_url())
        self.assertContains(response, "<time", count=2)
        self.assertContains(response, "Show 1 more")
        self.assertContains(response, f'wb-more" id="tension-{old.pk}"')

    def test_onto_the_agenda(self):
        """The owner puts their own tensions on the agenda, the secretary
        anybody's; removing the item puts it back into the inbox"""
        mine = self.tension(self.bob, "Knives dull", description="Since May")
        ada_s = self.tension(self.ada, "Oven broken")
        meeting = self.start()
        url = f"/meetings/{meeting.pk}/agenda/tensions/"

        self.client.force_login(self.bob)
        self.assertContains(self.client.get(meeting.get_absolute_url()), url)
        response = self.client.get(url)
        self.assertContains(response, "Knives dull")
        self.assertNotContains(response, "Oven broken")
        # Not others' tensions
        self.client.post(url, {"tensions": [mine.pk, ada_s.pk]})
        item = AgendaItem.objects.get()
        self.assertEqual((item.label, item.owner), ("Knives dull", self.bob))
        self.assertEqual(Tension.objects.open().get(), ada_s)

        # The description shows while it's processed
        self.client.force_login(self.ada)
        self.client.post(f"/meetings/{meeting.pk}/step/", {"step": "tensions"})
        self.client.post(f"/agenda/{item.pk}/process/")
        self.assertContains(self.client.get(meeting.get_absolute_url()), "Since May")

        self.client.post(f"/agenda/{item.pk}/remove/")
        self.assertEqual(Tension.objects.open().count(), 2)
        # The secretary adds the attendees', by owner
        response = self.client.get(url)
        self.assertContains(response, '<h2 class="h6 mb-0 me-auto">Bob</h2>', html=True)
        self.client.post(url, {"tensions": [mine.pk, ada_s.pk]})
        self.assertEqual(
            list(meeting.agenda_items.values_list("label", "owner")),
            # By owner, like the modal lists them
            [("Oven broken", self.ada.pk), ("Knives dull", self.bob.pk)],
        )
        self.assertFalse(Tension.objects.open().exists())
        meeting.agenda_items.all().delete()

        # Not tensions of people who aren't there
        meeting.attendees.remove(self.bob)
        self.client.post(url, {"tensions": [mine.pk]})
        self.assertNotContains(self.client.get(url), "Knives dull")
        self.assertTrue(Tension.objects.open().filter(pk=mine.pk).exists())

        # Only while the meeting runs
        meeting.agenda_items.all().delete()
        self.client.post(f"/meetings/{meeting.pk}/end/")
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_back_into_the_inbox(self):
        """Items left unprocessed go into the inbox when the meeting ends,
        also those typed in the meeting; processed ones and proposals don't"""
        done = self.tension(self.bob, "Knives dull")
        left = self.tension(self.bob, "Oven broken")
        meeting = self.start(kind="governance")
        self.client.post(
            f"/meetings/{meeting.pk}/agenda/tensions/",
            {"tensions": [done.pk, left.pk]},
        )
        self.client.post(f"/meetings/{meeting.pk}/agenda/add/", {"label": "Menu – Bob"})
        self.client.post(f"/meetings/{meeting.pk}/agenda/add/", {"label": "Prices"})
        draft = Proposal.objects.create(
            circle=self.kitchen,
            proposer=self.ada,
            role=self.kitchen.roles.get(core_role="secretary"),
            tension="Prices",
            created_at=meeting.started_at,
        )
        self.client.post(f"/meetings/{meeting.pk}/agenda/add/", {"proposal": draft.pk})
        AgendaItem.objects.get(tension=done).complete()
        # Due elections are on the agenda, not tensions
        self.assertTrue(meeting.agenda_items.filter(is_election=True).exists())
        self.client.post(f"/meetings/{meeting.pk}/end/")

        self.assertEqual(
            sorted(Tension.objects.open().values_list("title", "owner")),
            [
                ("Menu", self.bob.pk),
                ("Oven broken", self.bob.pk),
                ("Prices", self.ada.pk),
            ],
        )
        # Only once: the returned tension isn't added again as typed
        self.assertEqual(Tension.objects.filter(title="Oven broken").count(), 1)

    def test_capture_a_proposal(self):
        """In a governance meeting the secretary captures the proposal from
        it, with its description"""
        tension = self.tension(self.bob, "Knives dull", description="Since May")
        meeting = self.start(kind="governance")
        self.client.post(
            f"/meetings/{meeting.pk}/agenda/tensions/", {"tensions": [tension.pk]}
        )
        item = AgendaItem.objects.get(tension=tension)
        self.client.post(f"/meetings/{meeting.pk}/step/", {"step": "agenda"})
        self.client.post(f"/agenda/{item.pk}/process/")
        self.client.post(f"/agenda/{item.pk}/proposal/")
        proposal = Proposal.objects.get()
        self.assertEqual(proposal.tension, "Knives dull\n\nSince May")
        self.assertEqual((proposal.proposer, proposal.role), (self.bob, self.cook))

    def test_draft_a_proposal(self):
        """Its owner drafts a proposal from it, which takes it out of the
        inbox; deleting the draft puts it back"""
        tension = self.tension(self.bob, "Knives dull", description="Since May")
        self.client.force_login(self.bob)
        draft_url = f"/roles/{self.kitchen.pk}/proposals/new/?tension={tension.pk}"
        self.assertContains(
            self.client.get(self.kitchen.get_absolute_url()),
            f"?tension={tension.pk}",
        )
        response = self.client.get(draft_url)
        self.assertContains(response, "Knives dull\n\nSince May")
        self.client.post(draft_url, {"role": self.cook.pk, "tension": "Knives dull"})
        proposal = Proposal.objects.get()
        self.assertEqual(proposal.status, Proposal.DRAFT)
        tension.refresh_from_db()
        self.assertEqual(tension.proposal, proposal)
        self.assertFalse(Tension.objects.open().exists())
        proposal.delete()
        self.assertEqual(Tension.objects.open().get(), tension)

        # Not from others' tensions
        self.client.force_login(self.ada)
        self.assertNotContains(self.client.get(draft_url), "Since May")

    def test_person_page(self):
        """One's own page adds tensions to the circles' inboxes, one button
        per circle"""
        self.client.force_login(self.bob)
        response = self.client.get(self.bob.get_absolute_url())
        self.assertContains(response, f"/roles/{self.kitchen.pk}/tensions/new/", 1)
        self.assertNotContains(response, f"/roles/{self.sales.pk}/tensions/new/")
        # Not on others' pages
        response = self.client.get(self.ada.get_absolute_url())
        self.assertNotContains(response, "/tensions/new/")

    def test_private_on_person_page(self):
        """One's own private tensions are on one's page too, open ones only,
        with their circle; edited and deleted from there, back there"""
        private = self.tension(self.bob, "Knives dull", is_private=True)
        self.tension(self.bob, "Ovens hot")
        self.tension(self.ada, "Plates chipped", is_private=True)
        drafted = Proposal.objects.create(
            circle=self.kitchen, proposer=self.bob, created_at=timezone.now()
        )
        self.tension(self.bob, "Soup cold", is_private=True, proposal=drafted)
        self.client.force_login(self.bob)
        page = self.bob.get_absolute_url()
        response = self.client.get(page)
        self.assertContains(response, "Your private tensions")
        self.assertContains(response, "Knives dull")
        self.assertContains(response, "– Kitchen")
        self.assertContains(
            response, f"/roles/{self.kitchen.pk}/proposals/new/?tension={private.pk}"
        )
        for title in ["Ovens hot", "Plates chipped", "Soup cold"]:
            self.assertNotContains(response, title)
        delete_url = f"/tensions/{private.pk}/delete/?next={page}"
        self.assertContains(response, delete_url)
        self.assertRedirects(
            self.client.post(delete_url), page, fetch_redirect_response=False
        )
        self.assertNotContains(self.client.get(page), "Your private tensions")
        # Not on others' pages
        self.client.force_login(self.ada)
        self.assertNotContains(
            self.client.get(self.bob.get_absolute_url()), "Your private tensions"
        )


class DraftsIntoInboxesTest(TestCase):
    def test_migration(self):
        """Drafts without changes become private tensions in their circle's
        inbox, or go back to the tension they came from; not drafts with
        changes, on an agenda or in a role's inner circle"""
        from importlib import import_module

        from django.apps import apps

        migration = import_module(
            "governance.meetings.migrations.0009_drafts_into_inboxes"
        )
        ada = User.objects.create_user("ada@example.com", full_name="Ada")
        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        cook = Role.objects.create(name="Cook", circle=kitchen)
        long_ago = timezone.now() - dt.timedelta(days=400)
        test = {"op": "test", "path": f"/roles/{cook.pk}"}

        def draft(tension, *instructions, circle=kitchen):
            return Proposal.objects.create(
                circle=circle,
                proposer=ada,
                created_at=long_ago,
                tension=tension,
                instructions=list(instructions),
            )

        noted = draft(
            f"## The tension\n\nNo bread for @[Cook](role:{cook.pk})\n\n"
            "## An example\n\nToday",
            test,
        )
        one_line = draft("Soup")
        drafted = draft("## The tension\n\nKnives")
        source = Tension.objects.create(
            circle=kitchen, owner=ada, title="Knives", proposal=drafted
        )
        kept = [
            draft("Ovens", {"op": "add", "path": "/roles/n1"}),
            draft("Inside the cook", circle=cook),
        ]
        on_agenda = draft("Plates")
        meeting = Meeting.objects.create(
            circle=kitchen, kind=Meeting.GOVERNANCE, started_at=long_ago
        )
        AgendaItem.objects.create(meeting=meeting, proposal=on_agenda)
        kept.append(on_agenda)

        migration.drafts_into_inboxes(apps, None)

        self.assertEqual(
            set(Proposal.objects.values_list("pk", flat=True)),
            {p.pk for p in kept},
        )
        self.assertFalse(Proposal.objects.filter(pk__in=[noted.pk, one_line.pk]))
        source.refresh_from_db()
        self.assertIsNone(source.proposal)
        tensions = Tension.objects.exclude(pk=source.pk).order_by("title")
        self.assertEqual(
            [(t.title, t.is_private, t.owner, t.circle) for t in tensions],
            [
                ("No bread for @Cook", True, ada, kitchen),
                ("Soup", True, ada, kitchen),
            ],
        )
        self.assertEqual(tensions[0].description, noted.tension)
        self.assertEqual(tensions[0].created_at, long_ago)
        self.assertEqual(tensions[1].description, "")
