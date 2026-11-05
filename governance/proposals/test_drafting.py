import datetime as dt

import time_machine
from django.test import TestCase

from governance.accounts.models import User
from governance.proposals.instructions import ProposalError, adopt, problems
from governance.proposals.models import Proposal
from governance.roles.models import Accountability, Assignment, Domain, Policy, Role


@time_machine.travel(dt.datetime(2026, 12, 1, 12), tick=False)
class DraftingTest(TestCase):
    def setUp(self):
        self.ada = User.objects.create_user("ada@example.com", full_name="Ada")
        self.bob = User.objects.create_user("bob@example.com", full_name="Bob")
        self.kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        self.kitchen.create_core_roles()
        self.cook = Role.objects.create(name="Cook", circle=self.kitchen)
        self.cooking = Accountability.objects.create(role=self.cook, text="Cooking")
        self.frying = Accountability.objects.create(
            role=self.cook, text="Frying", position=1
        )
        self.tea = Policy.objects.create(role=self.kitchen, title="Tea", body="Always")
        Assignment.objects.create(
            role=self.cook, user=self.ada, starts_on=dt.date(2026, 1, 1)
        )
        self.client.force_login(self.ada)

    def draft(self):
        response = self.client.post(
            f"/roles/{self.kitchen.pk}/proposals/new/",
            {"role": self.cook.pk, "tension": "No bread"},
        )
        proposal = Proposal.objects.latest("pk")
        self.assertRedirects(response, proposal.get_absolute_url())
        return proposal

    def test_create_and_permissions(self):
        self.assertContains(
            self.client.get(f"/roles/{self.kitchen.pk}/"), "New proposal"
        )
        response = self.client.get(f"/roles/{self.kitchen.pk}/proposals/new/")
        self.assertContains(response, "Continue")
        self.assertContains(response, "## An example of a past or current situation")
        proposal = self.draft()
        self.assertEqual(
            (proposal.circle, proposal.proposer, proposal.status, proposal.tension),
            (self.kitchen, self.ada, Proposal.DRAFT, "No bread"),
        )
        self.assertContains(self.client.get(proposal.get_absolute_url()), "Add a role")
        self.client.post(
            f"/proposals/{proposal.pk}/tension/",
            {"role": self.cook.pk, "tension": "No tea"},
        )
        proposal.refresh_from_db()
        self.assertEqual(proposal.tension, "No tea")

        # Bob isn't a member of the kitchen, and the draft isn't his
        self.client.force_login(self.bob)
        self.assertEqual(
            self.client.get(f"/roles/{self.kitchen.pk}/proposals/new/").status_code,
            403,
        )
        self.assertEqual(
            self.client.get(f"/proposals/{proposal.pk}/roles/new/").status_code, 404
        )  # Drafts are private
        Proposal.objects.update(status=Proposal.PUBLISHED)
        self.assertEqual(
            self.client.get(f"/proposals/{proposal.pk}/roles/new/").status_code, 403
        )

        self.client.force_login(self.ada)
        Proposal.objects.update(status=Proposal.DRAFT)
        response = self.client.post(f"/proposals/{proposal.pk}/delete/")
        self.assertRedirects(response, f"/roles/{self.kitchen.pk}/")
        self.assertFalse(Proposal.objects.exists())

    def test_proposer_roles(self):
        from governance.roles.permissions import proposer_roles

        baker = Role.objects.create(name="Baker", circle=self.kitchen)
        waiter = Role.objects.create(name="Waiter", circle=self.kitchen)
        Assignment.objects.create(role=waiter, user=self.bob)
        # Ada proposes from her own role only
        self.assertEqual(list(proposer_roles(self.ada, self.kitchen)), [self.cook])
        response = self.client.post(
            f"/roles/{self.kitchen.pk}/proposals/new/",
            {"role": waiter.pk, "tension": "Not mine"},
        )
        self.assertEqual(response.status_code, 200)  # Not a valid choice
        self.assertFalse(Proposal.objects.exists())
        # The Circle Lead also from the roles nobody holds (and their own)
        lead = self.kitchen.roles.get(core_role="lead")
        Assignment.objects.create(role=lead, user=self.bob)
        self.assertEqual(
            set(proposer_roles(self.bob, self.kitchen)),
            {lead, waiter, baker}
            | set(
                self.kitchen.roles.filter(core_role__in=["facilitator", "secretary"])
            ),
        )
        proposal = self.draft()
        self.assertEqual(proposal.role, self.cook)
        self.assertContains(
            self.client.get(proposal.get_absolute_url()), "from the role"
        )

    def test_add_role(self):
        proposal = self.draft()
        response = self.client.post(
            f"/proposals/{proposal.pk}/roles/new/",
            {
                "name": "Baker",
                "purpose": "Bread",
                "new_accountabilities": "Baking\r\n\r\nSelling bread",
                "new_domains": "The oven",
            },
        )
        self.assertRedirects(response, proposal.get_absolute_url())
        proposal.refresh_from_db()
        self.assertEqual(
            [i["path"] for i in proposal.instructions],
            [
                "/roles/n1",
                "/roles/n1/name",
                "/roles/n1/aim",
                "/roles/n1/accountabilities/n2/description",
                "/roles/n1/accountabilities/n3/description",
                "/roles/n1/domains/n4/description",
            ],
        )
        response = self.client.get(proposal.get_absolute_url())
        self.assertContains(response, "Baker")
        self.assertContains(response, "Selling bread")
        self.assertContains(response, f"/proposals/{proposal.pk}/roles/n1/")

        # Editing it again
        response = self.client.get(f"/proposals/{proposal.pk}/roles/n1/")
        self.assertContains(response, "Selling bread")
        self.client.post(
            f"/proposals/{proposal.pk}/roles/n1/",
            {"name": "Baker", "purpose": "", "new_accountabilities": "Baking"},
        )
        proposal.refresh_from_db()
        self.assertEqual(len(proposal.instructions), 3)
        self.assertEqual(problems(proposal), [])

        adopt(proposal)
        baker = Role.objects.get(name="Baker")
        self.assertEqual(baker.circle, self.kitchen)
        self.assertEqual(
            list(baker.accountabilities.values_list("text", flat=True)), ["Baking"]
        )
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.ADOPTED)
        self.assertEqual(proposal.instructions[0]["path"], f"/roles/{baker.pk}")
        self.assertEqual(proposal.names, {f"roles/{baker.pk}": "Baker"})
        self.assertEqual(list(proposal.roles.all()), [baker])
        self.assertContains(
            self.client.get(proposal.get_absolute_url()), f'href="/roles/{baker.pk}/"'
        )
        with self.assertRaises(ProposalError):
            adopt(proposal)

    def test_anchor_circle_changes_its_own_purpose(self):
        """The kitchen is the anchor circle here (constitution 1.3.3)"""
        proposal = self.draft()
        response = self.client.get(proposal.get_absolute_url())
        self.assertContains(
            response, f"/proposals/{proposal.pk}/roles/{self.kitchen.pk}/"
        )
        self.client.post(
            f"/proposals/{proposal.pk}/roles/{self.kitchen.pk}/",
            {
                "name": "Kitchen",
                "purpose": "Food for all",
                "new_accountabilities": "Feeding",
            },
        )
        proposal.refresh_from_db()
        adopt(proposal)
        self.kitchen.refresh_from_db()
        self.assertEqual(self.kitchen.purpose, "Food for all")
        self.assertEqual(
            list(self.kitchen.accountabilities.values_list("text", flat=True)),
            ["Feeding"],
        )

        # It isn't removed, turned into a role or moved
        sub = Role.objects.create(name="Bakery", is_circle=True, circle=self.kitchen)
        for instructions in [
            [{"op": "remove", "path": f"/roles/{self.kitchen.pk}"}],
            [{"op": "remove", "path": f"/roles/{self.kitchen.pk}/supporting_circle"}],
            [
                {
                    "op": "move",
                    "from": f"/roles/{self.kitchen.pk}",
                    "path": f"/roles/{sub.pk}/supporting_circle/roles/{self.kitchen.pk}",
                }
            ],
        ]:
            other = Proposal.objects.create(
                circle=self.kitchen,
                proposer=self.ada,
                tension="x",
                created_at=proposal.created_at,
                instructions=instructions,
            )
            self.assertTrue(problems(other), instructions)
        # A sub-circle's purpose is still governed by its super-circle
        other = Proposal.objects.create(
            circle=sub,
            proposer=self.ada,
            tension="x",
            created_at=proposal.created_at,
            instructions=[
                {
                    "op": "replace",
                    "path": f"/roles/{sub.pk}/aim",
                    "original_value": "",
                    "value": "Bread",
                }
            ],
        )
        self.assertTrue(problems(other))

    def test_change_role(self):
        proposal = self.draft()
        url = f"/proposals/{proposal.pk}/roles/{self.cook.pk}/"
        self.client.post(
            url,
            {
                "name": "Chef",
                "purpose": "",
                f"accountabilities-{self.cooking.pk}": "Cooking food",
                f"accountabilities-{self.frying.pk}": "",
                "new_accountabilities": "Tasting",
            },
        )
        proposal.refresh_from_db()
        self.assertEqual(
            [(i["op"], i["path"]) for i in proposal.instructions],
            [
                ("test", f"/roles/{self.cook.pk}"),
                ("replace", f"/roles/{self.cook.pk}/name"),
                (
                    "replace",
                    (
                        f"/roles/{self.cook.pk}/accountabilities/"
                        f"{self.cooking.pk}/description"
                    ),
                ),
                ("remove", f"/roles/{self.cook.pk}/accountabilities/{self.frying.pk}"),
                ("add", f"/roles/{self.cook.pk}/accountabilities/n1/description"),
            ],
        )
        self.assertEqual(proposal.names, {f"roles/{self.cook.pk}": "Cook"})
        # The form shows the proposed values
        response = self.client.get(url)
        self.assertContains(response, 'value="Chef"')
        self.assertContains(response, "Tasting")

        # Somebody changed the role in the meantime
        Accountability.objects.filter(pk=self.cooking.pk).update(text="Cooking!")
        self.assertContains(
            self.client.get(proposal.get_absolute_url()),
            "has been changed since the proposal was drafted",
        )
        with self.assertRaises(ProposalError):
            adopt(proposal)
        self.cook.refresh_from_db()
        self.assertEqual(self.cook.name, "Cook")  # Nothing applied
        self.assertEqual(Accountability.objects.filter(role=self.cook).count(), 2)

        Accountability.objects.filter(pk=self.cooking.pk).update(text="Cooking")
        adopt(proposal)
        self.cook.refresh_from_db()
        self.assertEqual(self.cook.name, "Chef")
        self.assertEqual(
            list(self.cook.accountabilities.values_list("text", flat=True)),
            ["Cooking food", "Tasting"],
        )

    def test_undo_and_remove(self):
        proposal = self.draft()
        self.client.post(
            f"/proposals/{proposal.pk}/roles/{self.cook.pk}/",
            {
                "name": "Chef",
                f"accountabilities-{self.cooking.pk}": "Cooking",
                f"accountabilities-{self.frying.pk}": "Frying",
            },
        )
        self.client.post(f"/proposals/{proposal.pk}/roles/{self.cook.pk}/undo/")
        proposal.refresh_from_db()
        self.assertEqual((proposal.instructions, proposal.names), ([], {}))

        self.client.post(f"/proposals/{proposal.pk}/roles/{self.cook.pk}/remove/")
        self.client.post(f"/proposals/{proposal.pk}/policies/{self.tea.pk}/remove/")
        proposal.refresh_from_db()
        self.assertEqual(
            [i["op"] for i in proposal.instructions], ["test", "remove"] * 2
        )
        self.assertContains(self.client.get(proposal.get_absolute_url()), "Tea")
        adopt(proposal)
        self.cook.refresh_from_db()
        self.tea.refresh_from_db()
        self.assertEqual(self.cook.archived_on, dt.date(2026, 12, 1))
        self.assertEqual(self.tea.archived_on, dt.date(2026, 12, 1))
        self.assertEqual(Assignment.objects.get().ends_on, dt.date(2026, 12, 1))

    def test_policies(self):
        proposal = self.draft()
        self.client.post(
            f"/proposals/{proposal.pk}/policies/new/",
            {"title": "Bread", "body": "Daily"},
        )
        self.client.post(
            f"/proposals/{proposal.pk}/policies/{self.tea.pk}/",
            {"title": "Tea", "body": "Often"},
        )
        proposal.refresh_from_db()
        url = f"/proposals/{proposal.pk}/policies/{self.tea.pk}/"
        self.assertContains(self.client.get(url), "Often")
        self.assertNotContains(self.client.get(url), "Changed in the meantime")
        # Changed in the meantime: the form shows the current text
        Policy.objects.filter(pk=self.tea.pk).update(body="<b>Never</b>")
        self.assertContains(
            self.client.get(url),
            "Changed in the meantime, currently: &lt;b&gt;Never&lt;/b&gt;",
        )
        Policy.objects.filter(pk=self.tea.pk).update(body=self.tea.body)
        adopt(proposal)
        self.tea.refresh_from_db()
        self.assertEqual(self.tea.body, "Often")
        bread = Policy.objects.get(title="Bread")
        self.assertEqual((bread.role, bread.body), (self.kitchen, "Daily"))

    def test_circle_lead_stays_as_defined(self):
        lead = self.kitchen.roles.get(core_role="lead")
        proposal = self.draft()
        self.assertNotContains(
            self.client.get(proposal.get_absolute_url()),
            f"/proposals/{proposal.pk}/roles/{lead.pk}/",
        )
        self.assertEqual(
            self.client.get(f"/proposals/{proposal.pk}/roles/{lead.pk}/").status_code,
            403,
        )
        proposal.instructions = [
            {
                "op": "add",
                "path": f"/roles/{lead.pk}/accountabilities/n1/description",
                "value": "Hiring",
            },
        ]
        self.assertEqual(
            problems(proposal), ["The Circle Lead gets no accountabilities or domains."]
        )

    def test_constitution(self):
        lead = self.kitchen.roles.get(core_role="lead")
        proposal = Proposal.objects.create(
            circle=self.kitchen,
            proposer=self.ada,
            tension="Rules",
            created_at=dt.datetime(2026, 12, 1, tzinfo=dt.UTC),
            instructions=[
                {"op": "replace", "path": f"/roles/{lead.pk}/name", "value": "Boss"},
                {"op": "remove", "path": f"/roles/{lead.pk}"},
                {"op": "test", "path": f"/roles/{self.kitchen.pk}"},
                {"op": "add", "path": "/roles/n1"},
                {"op": "move", "path": f"/roles/{self.cook.pk}"},
            ],
        )
        self.assertEqual(
            problems(proposal),
            [
                # Once, although two instructions change the Circle Lead
                "The constitution defines Circle Lead.",
                f"The app can't apply /roles/{self.cook.pk} yet.",
                "A new role or policy needs a name.",
            ],
        )

        # Secretary, Facilitator and Circle Rep may get accountabilities
        secretary = self.kitchen.roles.get(core_role="secretary")
        self.client.post(
            f"/proposals/{self.draft().pk}/roles/{secretary.pk}/",
            {"new_accountabilities": "Ordering supplies"},
        )
        adopt(Proposal.objects.latest("pk"))
        self.assertEqual(Domain.objects.count(), 0)
        self.assertEqual(secretary.accountabilities.get().text, "Ordering supplies")

    def test_remove_circle(self):
        """Selected roles and policies move to the super-circle, the rest goes"""
        bakery = Role.objects.create(name="Bakery", is_circle=True, circle=self.kitchen)
        bakery.create_core_roles()
        baker = Role.objects.create(name="Baker", circle=bakery)
        cleaner = Role.objects.create(name="Cleaner", circle=bakery)
        oven = Role.objects.create(name="Oven", is_circle=True, circle=bakery)
        heater = Role.objects.create(name="Heater", circle=oven)
        flour = Policy.objects.create(role=bakery, title="Flour")
        noise = Policy.objects.create(role=bakery, title="Noise")
        Assignment.objects.create(role=cleaner, user=self.bob)
        proposal = self.draft()
        self.assertContains(
            self.client.get(proposal.get_absolute_url()),
            f"/proposals/{proposal.pk}/roles/{bakery.pk}/remove-circle/",
        )
        url = f"/proposals/{proposal.pk}/roles/{bakery.pk}/remove-circle/"
        self.assertContains(self.client.get(url), "Baker")
        self.client.post(url, {"roles": [baker.pk], "policies": [flour.pk]})
        self.client.post(
            url, {"roles": [baker.pk], "policies": [flour.pk]}
        )  # Not twice
        proposal.refresh_from_db()
        self.assertEqual(sum(1 for i in proposal.instructions if i["op"] == "move"), 2)
        self.assertContains(self.client.get(proposal.get_absolute_url()), "Bakery")
        adopt(proposal)
        for obj in [baker, cleaner, oven, heater, bakery, flour, noise]:
            obj.refresh_from_db()
        self.assertEqual((baker.circle, baker.archived_on), (self.kitchen, None))
        self.assertEqual((flour.role, flour.archived_on), (self.kitchen, None))
        self.assertTrue(
            all(o.archived_on for o in [cleaner, oven, heater, bakery, noise])
        )
        self.assertFalse(Assignment.objects.current().filter(role=cleaner).exists())
        # Only circles, not the anchor
        other = self.draft()
        for role in [self.cook, self.kitchen]:
            self.assertEqual(
                self.client.get(
                    f"/proposals/{other.pk}/roles/{role.pk}/remove-circle/"
                ).status_code,
                403,
            )

    def test_remove_circle_keeps_moves(self):
        """The form starts with what the proposal moves out of the circle
        already: saving it again doesn't drop those moves"""
        bakery = Role.objects.create(name="Bakery", is_circle=True, circle=self.kitchen)
        bakery.create_core_roles()
        baker = Role.objects.create(name="Baker", circle=bakery)
        noise = Policy.objects.create(role=bakery, title="Noise")
        proposal = self.draft()
        self.client.post(
            f"/proposals/{proposal.pk}/move/", {"kind": "policies", "key": noise.pk}
        )
        url = f"/proposals/{proposal.pk}/roles/{bakery.pk}/remove-circle/"
        form = self.client.get(url).context["form"]
        self.assertEqual(
            (form["roles"].initial, form["policies"].initial), ([], [noise.pk])
        )
        self.client.post(url, {"roles": [baker.pk], "policies": [noise.pk]})
        form = self.client.get(url).context["form"]
        self.assertEqual(
            (form["roles"].initial, form["policies"].initial), ([baker.pk], [noise.pk])
        )

    def test_circle_without_roles_turns_back(self):
        """Moving or removing a circle's last role turns it back into a role"""
        bakery = Role.objects.create(name="Bakery", is_circle=True, circle=self.kitchen)
        bakery.create_core_roles()
        Assignment.objects.create(
            role=bakery.roles.get(core_role="secretary"), user=self.bob
        )
        baker = Role.objects.create(name="Baker", circle=bakery)
        proposal = self.draft()
        proposal.instructions = [
            {
                "op": "move",
                "path": f"/roles/{baker.pk}",
                "from": f"/circles/{bakery.pk}/roles/{baker.pk}",
            }
        ]
        proposal.names = {
            f"roles/{baker.pk}": "Baker",
            f"circles/{bakery.pk}": "Bakery",
        }
        proposal.save()
        response = self.client.get(proposal.get_absolute_url())
        self.assertContains(response, "Bakery loses its last roles")
        adopt(proposal)
        bakery.refresh_from_db()
        baker.refresh_from_db()
        self.assertEqual((bakery.is_circle, baker.circle), (False, self.kitchen))
        self.assertFalse(bakery.roles.active().exists())
        self.assertFalse(Assignment.objects.current().filter(user=self.bob).exists())
        proposal.refresh_from_db()
        self.assertEqual(
            proposal.instructions[-1],
            {"op": "remove", "path": f"/roles/{bakery.pk}/supporting_circle"},
        )
        self.assertContains(
            self.client.get(proposal.get_absolute_url()), "Turned back into a role"
        )

        # A circle keeping roles stays a circle
        other = Role.objects.create(name="Pastry", is_circle=True, circle=self.kitchen)
        other.create_core_roles()
        first = Role.objects.create(name="Icing", circle=other)
        Role.objects.create(name="Dough", circle=other)
        proposal = Proposal.objects.create(
            circle=other,
            proposer=self.ada,
            tension="Less icing",
            created_at=proposal.created_at,
            instructions=[{"op": "remove", "path": f"/roles/{first.pk}"}],
        )
        adopt(proposal)
        other.refresh_from_db()
        self.assertTrue(other.is_circle)

    def test_roles_inside_a_role(self):
        """The role's holders add roles inside it, which makes it a circle"""
        self.assertContains(
            self.client.get(self.cook.get_absolute_url()), "New proposal"
        )
        self.client.post(
            f"/roles/{self.cook.pk}/proposals/new/",
            {"role": self.cook.pk, "tension": "Too much to do"},
        )
        proposal = Proposal.objects.latest("pk")
        self.assertEqual((proposal.circle, proposal.role), (self.cook, self.cook))
        self.client.post(
            f"/proposals/{proposal.pk}/roles/new/", {"name": "Sous-chef", "purpose": ""}
        )
        # Ada is the role's only holder: adopted when publishing
        self.client.post(f"/proposals/{proposal.pk}/publish/")
        proposal.refresh_from_db()
        self.cook.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.ADOPTED)
        self.assertTrue(self.cook.is_circle)
        self.assertTrue(self.cook.roles.filter(name="Sous-chef").exists())
        lead = self.cook.roles.get(core_role="lead")
        self.assertEqual(Assignment.objects.current().get(role=lead).user, self.ada)
        self.assertEqual(
            proposal.instructions[0],
            {"op": "add", "path": f"/roles/{self.cook.pk}/supporting_circle"},
        )

        # Others don't
        self.client.force_login(self.bob)
        waiter = Role.objects.create(name="Waiter", circle=self.kitchen)
        self.assertEqual(
            self.client.get(f"/roles/{waiter.pk}/proposals/new/").status_code, 403
        )

    def test_move_into_a_role(self):
        """The circle moves roles into one of its roles, which becomes a circle"""
        waiter = Role.objects.create(name="Waiter", circle=self.kitchen)
        proposal = self.draft()
        self.assertContains(
            self.client.get(f"/proposals/{proposal.pk}/move/"),
            "Roles moved into a role make it a circle.",
        )
        self.client.post(
            f"/proposals/{proposal.pk}/move/",
            {"kind": "roles", "key": waiter.pk, "target": self.cook.pk},
        )
        adopt(Proposal.objects.get(pk=proposal.pk))
        self.cook.refresh_from_db()
        waiter.refresh_from_db()
        self.assertEqual((self.cook.is_circle, waiter.circle), (True, self.cook))

    def test_convert(self):
        proposal = self.draft()
        url = f"/proposals/{proposal.pk}/roles/{self.cook.pk}/convert/"
        self.client.post(url)
        self.client.post(url)  # Undone
        proposal.refresh_from_db()
        self.assertEqual(proposal.instructions, [])
        self.client.post(url)
        self.assertContains(
            self.client.get(proposal.get_absolute_url()), "Turned into a circle"
        )
        adopt(Proposal.objects.get())
        self.cook.refresh_from_db()
        self.assertTrue(self.cook.is_circle)
        lead = self.cook.roles.get(core_role="lead")
        self.assertEqual(Assignment.objects.current().get(role=lead).user, self.ada)
        self.assertEqual(
            Assignment.objects.current().get(role=self.cook).user, self.ada
        )

        # And back: the circle's core roles go
        proposal = self.draft()
        self.client.post(f"/proposals/{proposal.pk}/roles/{self.cook.pk}/convert/")
        adopt(Proposal.objects.get(pk=proposal.pk))
        self.cook.refresh_from_db()
        self.assertFalse(self.cook.is_circle)
        self.assertFalse(self.cook.roles.active().exists())

    def test_gone(self):
        """Objects removed since the proposal was drafted"""
        sub = Role.objects.create(name="Bakery", circle=self.kitchen, is_circle=True)
        sub.create_core_roles()
        Role.objects.create(name="Baker", circle=sub)
        proposal = Proposal.objects.create(
            circle=self.kitchen,
            proposer=self.ada,
            tension="Gone",
            created_at=dt.datetime(2026, 12, 1, tzinfo=dt.UTC),
            names={"roles/999": "Waiter"},
            instructions=[
                {"op": "test", "path": "/roles/999"},
                {
                    "op": "remove",
                    "path": f"/roles/{self.cook.pk}/accountabilities/999",
                    "original_value": "Dancing",
                },
                {"op": "remove", "path": f"/roles/{sub.pk}/supporting_circle"},
                {"op": "add", "path": "/roles/n5/name", "value": "Ghost"},
            ],
        )
        self.assertEqual(
            problems(proposal),
            [
                "Waiter doesn't exist anymore.",
                "Dancing doesn't exist anymore.",
                "Bakery still has roles, they have to go first.",
                "The proposal refers to n5 before adding it.",
            ],
        )

    def test_move(self):
        bakery = Role.objects.create(name="Bakery", circle=self.kitchen, is_circle=True)
        bakery.create_core_roles()
        baker = Role.objects.create(name="Baker", circle=bakery)
        flour = Policy.objects.create(role=bakery, title="Flour")
        proposal = self.draft()
        url = f"/proposals/{proposal.pk}/move/"
        response = self.client.get(url)
        self.assertContains(response, "Baker")
        self.assertContains(response, "Move into Kitchen")

        self.client.post(
            url, {"kind": "roles", "key": self.cook.pk, "target": bakery.pk}
        )
        self.client.post(
            url, {"kind": "policies", "key": self.tea.pk, "target": bakery.pk}
        )
        self.client.post(url, {"kind": "roles", "key": baker.pk})
        self.client.post(url, {"kind": "policies", "key": flour.pk})
        # Moving the bakery into itself
        self.assertEqual(
            self.client.post(
                url, {"kind": "roles", "key": bakery.pk, "target": bakery.pk}
            ).status_code,
            403,
        )
        proposal.refresh_from_db()
        self.assertEqual(
            [(i["op"], i["path"]) for i in proposal.instructions][:2],
            [
                ("test", f"/roles/{self.cook.pk}"),
                ("move", f"/roles/{bakery.pk}/supporting_circle/roles/{self.cook.pk}"),
            ],
        )
        response = self.client.get(proposal.get_absolute_url())
        self.assertContains(response, "into Bakery")
        self.assertContains(response, "from Bakery")
        self.assertNotContains(
            response, f'href="/proposals/{proposal.pk}/roles/{baker.pk}/"'
        )
        self.assertEqual(problems(proposal), [])

        adopt(proposal)
        for obj in [self.cook, self.tea, baker, flour]:
            obj.refresh_from_db()
        self.assertEqual(
            (self.cook.circle, self.tea.role, baker.circle, flour.role),
            (bakery, bakery, self.kitchen, self.kitchen),
        )

    def test_move_problems(self):
        lead = self.kitchen.roles.get(core_role="lead")
        domain_policy = Policy.objects.create(role=self.cook, title="Stove")
        proposal = Proposal.objects.create(
            circle=self.kitchen,
            proposer=self.ada,
            tension="Moves",
            created_at=dt.datetime(2026, 12, 1, tzinfo=dt.UTC),
            instructions=[
                {
                    "op": "move",
                    "path": f"/roles/{self.cook.pk}/supporting_circle/roles/{lead.pk}",
                    "from": f"/roles/{lead.pk}",
                },
                {
                    "op": "move",
                    "path": f"/roles/{self.cook.pk}",
                    "from": f"/circles/{self.cook.pk}/roles/{self.cook.pk}",
                },
                {"op": "move", "path": f"/policies/{domain_policy.pk}", "from": ""},
            ],
        )
        self.assertEqual(
            problems(proposal),
            [
                # Moving into Cook makes it a circle, but not the Circle Lead
                "Circle Lead can't be moved.",
                "Cook isn't governed by Cook.",
                f"The app can't apply /policies/{domain_policy.pk} yet.",
            ],
        )
