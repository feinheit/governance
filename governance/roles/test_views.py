import datetime as dt

from django.test import TestCase
from django.utils import timezone

from governance.accounts.models import User
from governance.proposals.models import Proposal
from governance.roles.models import (
    Accountability,
    Assignment,
    ChecklistItem,
    Domain,
    Metric,
    Policy,
    Role,
)
from governance.roles.permissions import proposer_roles


class ViewsTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("ada@example.com", full_name="Ada Example")
        self.client.force_login(self.user)

    def test_start(self):
        """The start page is the own page, the organization a link away"""
        self.assertRedirects(self.client.get("/"), self.user.get_absolute_url())
        response = self.client.get("/organization/")
        self.assertContains(response, "There is no anchor circle yet.")
        anchor = Role.objects.create(name="Example Ltd", is_circle=True)
        self.assertRedirects(
            self.client.get("/organization/"), anchor.get_absolute_url()
        )

    def test_person_shows_circles(self):
        anchor = Role.objects.create(name="Example Ltd", is_circle=True)
        kitchen = Role.objects.create(name="Kitchen", is_circle=True, circle=anchor)
        cook = Role.objects.create(name="Cook", circle=anchor)
        Assignment.objects.create(role=kitchen, user=self.user)
        Assignment.objects.create(role=cook, user=self.user)

        response = self.client.get(self.user.get_absolute_url())
        # The Kitchen, not the Cook
        self.assertContains(
            response,
            '<span class="badge wb-tone-circle">Circle</span>',
            count=1,
            html=True,
        )

    def test_one_link_for_tactical_meetings(self):
        """Circles and roles link to an ad-hoc tactical meeting once"""
        anchor = Role.objects.create(name="Example Ltd", is_circle=True)
        kitchen = Role.objects.create(name="Kitchen", is_circle=True, circle=anchor)
        kitchen.create_core_roles()
        cook = Role.objects.create(name="Cook", circle=kitchen)
        for role in [anchor, kitchen, cook]:
            with self.subTest(role=role):
                response = self.client.get(role.get_absolute_url())
                self.assertContains(
                    response, f"/meetings/tactical/new/?role={role.pk}", count=1
                )
                self.assertContains(response, "Call a tactical meeting", count=1)

    def test_proposals_inside_a_role(self):
        """A role links to the proposals inside it, e.g. from its time as a
        circle"""
        anchor = Role.objects.create(name="Example Ltd", is_circle=True)
        bakery = Role.objects.create(name="Bakery", circle=anchor)
        url = f"/proposals/?circle={bakery.pk}"
        self.assertNotContains(self.client.get(bakery.get_absolute_url()), url)
        Proposal.objects.create(
            circle=bakery,
            proposer=self.user,
            tension="Bread",
            status=Proposal.ADOPTED,
            created_at=timezone.now(),
        )
        response = self.client.get(bakery.get_absolute_url())
        self.assertContains(response, url)
        self.assertContains(response, "All proposals inside this role")

    def test_person_earlier_roles_show_more(self):
        anchor = Role.objects.create(name="Example Ltd", is_circle=True)
        for day in range(1, 9):
            Assignment.objects.create(
                role=Role.objects.create(name=f"Role {day}", circle=anchor),
                user=self.user,
                ends_on=dt.date(2026, 1, day),
            )

        response = self.client.get(self.user.get_absolute_url())
        # The latest five, the other three on request (in the page: only
        # the CSS hides them, and only with JavaScript)
        self.assertContains(response, "Show 3 more")
        self.assertContains(response, "wb-more", count=3)
        self.assertContains(response, "Role 1")

    def test_long_proposal_lists_show_more(self):
        anchor = Role.objects.create(name="Example Ltd", is_circle=True)
        Assignment.objects.create(
            role=Role.objects.create(name="Cook", circle=anchor), user=self.user
        )
        for index in range(8):
            for status in [Proposal.DRAFT, Proposal.PUBLISHED]:
                Proposal.objects.create(
                    circle=anchor,
                    proposer=self.user,
                    status=status,
                    tension=f"Tension {index}",
                    created_at=timezone.now(),
                )

        # The circle's pending proposals, one's drafts
        for url in [anchor.get_absolute_url(), self.user.get_absolute_url()]:
            response = self.client.get(url)
            self.assertContains(response, "Show 3 more")
            self.assertContains(response, "wb-more", count=3)

        # A role's history: the latest ten, five on request
        cook = Role.objects.get(name="Cook")
        for proposal in Proposal.objects.filter(status=Proposal.PUBLISHED):
            proposal.status = Proposal.ADOPTED
            proposal.save()
            proposal.roles.add(cook)
        response = self.client.get(cook.get_absolute_url())
        self.assertContains(response, "Show 3 more")
        self.assertContains(response, "wb-more", count=3)

    def test_circle_lead_without_accountabilities(self):
        """The Circle Lead holds what no role covers (constitution 1.4)"""
        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        kitchen.create_core_roles()
        lead = kitchen.roles.get(core_role="lead")
        response = self.client.get(lead.get_absolute_url())
        self.assertContains(response, "as far as no role or process")
        facilitator = kitchen.roles.get(core_role="facilitator")
        response = self.client.get(facilitator.get_absolute_url())
        self.assertNotContains(response, "as far as no role or process")

    def test_role_page_policies_and_proposals_inside(self):
        """A role's page shows the policies of its circles, which apply to
        it, and the pending proposals for its inside (1.3.1)"""
        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        kitchen.create_core_roles()
        Policy.objects.create(role=kitchen, title="Clean up", body="Always")
        cook = Role.objects.create(name="Cook", circle=kitchen)
        Proposal.objects.create(
            circle=cook,
            proposer=self.user,
            role=cook,
            tension="Too much to do",
            status=Proposal.PUBLISHED,
            created_at=timezone.now(),
        )
        response = self.client.get(cook.get_absolute_url())
        self.assertContains(response, "Clean up")
        self.assertContains(response, "Too much to do")

    def test_new_proposal_only_for_proposers(self):
        """Admins outside the circle don't get "New proposal", which would
        refuse them"""
        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        kitchen.create_core_roles()
        self.user.is_admin = True
        self.user.save()
        self.assertNotContains(
            self.client.get(kitchen.get_absolute_url()), "New proposal"
        )

    def test_unassigned_role_held_by_the_circle_lead(self):
        anchor = Role.objects.create(name="Example Ltd", is_circle=True)
        kitchen = Role.objects.create(name="Kitchen", is_circle=True, circle=anchor)
        kitchen.create_core_roles()
        Assignment.objects.create(
            role=kitchen.roles.get(core_role="lead"), user=self.user
        )
        cook = Role.objects.create(name="Cook", circle=kitchen)
        response = self.client.get(cook.get_absolute_url())
        self.assertContains(response, "the Circle Leads (by default)")
        self.assertContains(response, self.user.get_absolute_url())
        self.assertNotContains(response, "Held by the Circle Leads")

        # The Circle Lead isn't eligible for the Circle Rep, an unfilled one
        # is nobody's (also not a role to propose from)
        rep = kitchen.roles.get(core_role="rep")
        response = self.client.get(rep.get_absolute_url())
        self.assertNotContains(response, "the Circle Leads (by default)")
        self.assertContains(response, "Nobody")
        self.assertNotIn(rep, proposer_roles(self.user, kitchen))
        self.assertIn(cook, proposer_roles(self.user, kitchen))

    def test_circle_lists_sub_circles_among_roles(self):
        anchor = Role.objects.create(name="Example Ltd", is_circle=True)
        anchor.create_core_roles()
        Role.objects.create(name="Kitchen", is_circle=True, circle=anchor)
        Role.objects.create(name="Cook", circle=anchor)

        response = self.client.get(anchor.get_absolute_url())
        self.assertNotContains(response, "Sub-circles")
        # The Kitchen, not the Cook
        self.assertContains(
            response,
            '<span class="badge wb-tone-circle">Circle</span>',
            count=1,
            html=True,
        )
        roles = response.context["roles"]
        self.assertEqual([role.name for role in roles], ["Cook", "Kitchen"])

    def test_circle_and_roles(self):
        anchor = Role.objects.create(
            name="Example Ltd",
            is_circle=True,
            purpose="Tea for all",
            strategy="**Tea** first",
        )
        anchor.create_core_roles()
        kitchen = Role.objects.create(name="Kitchen", is_circle=True, circle=anchor)
        kitchen.create_core_roles()
        cook = Role.objects.create(name="Cook", circle=kitchen, purpose="Food")
        Role.objects.create(name="Dishwasher", circle=kitchen)
        Accountability.objects.create(role=cook, text="Cooking *daily*")
        domain = Domain.objects.create(role=cook, text="The stove")
        policy = Policy.objects.create(
            role=cook, title="Stove", body="Off at night", domain=domain
        )
        Metric.objects.create(
            role=cook,
            description="Meals",
            frequency="Weekly",
            link="https://example.com/",
        )
        ChecklistItem.objects.create(role=cook, description="Stove off")
        Assignment.objects.create(
            role=cook, user=self.user, focus="Soups", starts_on=dt.date(2026, 1, 1)
        )
        lead = kitchen.roles.get(core_role="lead")
        Assignment.objects.create(role=lead, user=self.user)

        # Holders of the kitchen's role in the anchor circle: lead and rep
        bob = User.objects.create_user("bob@example.com", full_name="Bob Example")
        Assignment.objects.create(role=kitchen, user=self.user)
        Assignment.objects.create(role=kitchen, user=bob)
        Assignment.objects.create(role=kitchen.roles.get(core_role="rep"), user=bob)

        response = self.client.get(anchor.get_absolute_url())
        self.assertContains(response, "(Circle Rep)", count=1)  # Bob, not Ada
        # The circle's own page: its holders are those of its core roles,
        # first in the sidebar
        kitchen_page = self.client.get(kitchen.get_absolute_url()).content.decode()
        self.assertNotIn("(Circle Rep)", kitchen_page)
        self.assertLess(
            kitchen_page.index("Core roles"), kitchen_page.index("Meetings")
        )
        self.assertContains(response, "<strong>Tea</strong> first")
        self.assertContains(response, "Kitchen")
        self.assertNotContains(response, ">Circle Rep</a>")  # Not in the anchor circle

        response = self.client.get(kitchen.get_absolute_url())
        self.assertContains(response, "Circle Rep")
        self.assertContains(response, "Held by the Circle Leads")  # The dishwasher
        response = self.client.get(
            kitchen.roles.get(core_role="secretary").get_absolute_url()
        )
        self.assertContains(response, "Scheduling Governance Meetings for the Circle")
        self.assertContains(response, "All governance records of the Circle")

        response = self.client.get(
            anchor.roles.get(core_role="lead").get_absolute_url()
        )
        self.assertContains(response, "Nobody")
        self.assertContains(
            response, "Tea for all"
        )  # The Circle Lead holds the purpose
        response = self.client.get(lead.get_absolute_url())
        self.assertContains(response, "Ada Example")
        response = self.client.get(cook.get_absolute_url())
        self.assertContains(response, "Cooking <em>daily</em>")
        self.assertContains(response, "The stove")
        self.assertContains(response, "Soups")
        self.assertContains(response, "Meals")
        self.assertContains(response, "Stove off")
        self.assertContains(response, policy.get_absolute_url())

        # The super-circle's policies apply in the kitchen too
        Policy.objects.create(role=anchor, title="Tea time", body="At four")
        response = self.client.get(kitchen.get_absolute_url())
        self.assertContains(response, "Tea time")
        self.assertContains(response, "From the super-circle")
        self.assertNotContains(
            self.client.get(anchor.get_absolute_url()), "From the super-circle"
        )

        response = self.client.get(policy.get_absolute_url())
        self.assertContains(response, "Off at night")

        response = self.client.get("/people/")
        self.assertContains(response, self.user.get_absolute_url())
        response = self.client.get(self.user.get_absolute_url())
        self.assertContains(response, "Soups")

        Assignment.objects.filter(role=cook).update(ends_on=dt.date(2026, 2, 1))
        response = self.client.get(self.user.get_absolute_url())
        self.assertContains(response, "Earlier roles")
