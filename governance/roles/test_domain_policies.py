from django.core import mail
from django.test import TestCase

from governance.accounts.models import User
from governance.proposals.models import Proposal
from governance.roles.models import Assignment, Domain, Policy, Role


class DomainPoliciesTest(TestCase):
    """A role regulates its domains with its own policies (1.3.2)"""

    def setUp(self):
        self.ada = User.objects.create_user("ada@example.com", full_name="Ada")
        self.bob = User.objects.create_user("bob@example.com", full_name="Bob")
        self.eve = User.objects.create_user("eve@example.com", full_name="Eve")
        self.max = User.objects.create_user(
            "max@example.com", full_name="Max", notify_all=True
        )
        self.anchor = Role.objects.create(name="Example Ltd", is_circle=True)
        self.anchor.create_core_roles()
        self.web = Role.objects.create(name="Web", is_circle=True, circle=self.anchor)
        self.web.create_core_roles()
        self.hosting = Role.objects.create(
            name="Hosting", is_circle=True, circle=self.web
        )
        self.hosting.create_core_roles()
        self.admin = Role.objects.create(name="Server admin", circle=self.web)
        self.servers = Domain.objects.create(role=self.admin, text="Server access")
        Assignment.objects.create(role=self.admin, user=self.ada)
        # Members of the circle and of its sub-circle are affected
        Assignment.objects.create(
            role=Role.objects.create(name="Developer", circle=self.web), user=self.bob
        )
        Assignment.objects.create(
            role=Role.objects.create(name="Mailer", circle=self.hosting), user=self.eve
        )
        self.url = f"/roles/{self.admin.pk}/domain-policies/new/"

    def test_role_leads_change_policies(self):
        self.client.force_login(self.ada)
        response = self.client.get(f"/roles/{self.admin.pk}/")
        # On the domain's line, no card of policies without any
        self.assertContains(response, f"{self.url}?domain={self.servers.pk}")
        self.assertNotContains(response, '<h2 class="h6 mb-0">Policies</h2>')
        # The domain chosen already
        self.assertContains(
            self.client.get(f"{self.url}?domain={self.servers.pk}"),
            f'<option value="{self.servers.pk}" selected>',
        )
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                self.url,
                {
                    "title": "Server access",
                    "body": "Developers on request",
                    "domain": self.servers.pk,
                },
            )
        self.assertRedirects(response, self.admin.get_absolute_url())
        policy = Policy.objects.get()
        # The domain links to its policies (frontend/open_details.js)
        response = self.client.get(self.admin.get_absolute_url())
        self.assertContains(response, f'href="#policy-{policy.pk}"')
        self.assertContains(response, f'data-open-details="policy-{policy.pk}"')
        self.assertContains(response, f'id="policy-{policy.pk}"')
        self.assertContains(response, "1 policy")
        self.assertContains(response, '<h2 class="h6 mb-0">Policies</h2>')
        self.assertEqual((policy.role, policy.domain), (self.admin, self.servers))
        proposal = Proposal.objects.get()
        self.assertEqual(
            (
                proposal.status,
                proposal.circle,
                proposal.role,
                proposal.proposer,
            ),
            (Proposal.ADOPTED, self.web, self.admin, self.ada),
        )
        self.assertEqual(list(proposal.policies.all()), [policy])
        self.assertEqual(
            sorted(m.to[0] for m in mail.outbox),
            [
                "ada@example.com",
                "bob@example.com",
                "eve@example.com",
                "max@example.com",
            ],
        )
        self.assertIn("Developers on request", mail.outbox[0].body)
        self.assertIn("applies in Web and its sub-circles", mail.outbox[0].body)
        # Names who changed it, except to them
        bodies = {m.to[0]: m.body for m in mail.outbox}
        self.assertIn("Changed by Ada.", bodies["bob@example.com"])
        self.assertNotIn("Changed by", bodies["ada@example.com"])
        self.assertContains(
            self.client.get(proposal.get_absolute_url()), "Developers on request"
        )

        # Changing it records only what changed
        mail.outbox = []
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                f"/roles/{self.admin.pk}/domain-policies/{policy.pk}/",
                {
                    "title": "Server access",
                    "body": "Developers always",
                    "domain": self.servers.pk,
                },
            )
        change = Proposal.objects.latest("pk")
        self.assertEqual(
            change.instructions,
            [
                {
                    "op": "replace",
                    "path": f"/policies/{policy.pk}/body",
                    "original_value": "Developers on request",
                    "value": "Developers always",
                }
            ],
        )
        self.assertEqual(len(mail.outbox), 4)
        # Saving without a change records nothing
        self.client.post(
            f"/roles/{self.admin.pk}/domain-policies/{policy.pk}/",
            {
                "title": "Server access",
                "body": "Developers always",
                "domain": self.servers.pk,
            },
        )
        self.assertEqual(Proposal.objects.count(), 2)

        # Asked first, e.g. in a modal
        remove_url = f"/roles/{self.admin.pk}/domain-policies/{policy.pk}/remove/"
        self.assertContains(
            self.client.get(remove_url), "Remove the policy Server access?"
        )
        self.assertEqual(Proposal.objects.count(), 2)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(remove_url)
        policy.refresh_from_db()
        self.assertIsNotNone(policy.archived_on)
        self.assertEqual(Proposal.objects.latest("pk").instructions[0]["op"], "remove")

    def test_permissions(self):
        circle_policy = Policy.objects.create(role=self.web, title="Tea")
        # Others don't, not the circle's policies, not roles without domains
        self.client.force_login(self.bob)
        self.assertNotContains(
            self.client.get(f"/roles/{self.admin.pk}/"), "/domain-policies/new/"
        )
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_login(self.ada)
        self.assertEqual(
            self.client.get(
                f"/roles/{self.admin.pk}/domain-policies/{circle_policy.pk}/"
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(f"/roles/{self.web.pk}/domain-policies/new/").status_code,
            403,
        )
        self.servers.delete()
        self.assertEqual(self.client.get(self.url).status_code, 403)

        # Nobody holds the role: its circle's Circle Lead
        Domain.objects.create(role=self.admin, text="Server access")
        Assignment.objects.all().delete()
        Assignment.objects.create(
            role=self.web.roles.get(core_role="lead"), user=self.eve
        )
        self.client.force_login(self.eve)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_restructuring(self):
        """The policies go with their role and domain: moved with the role,
        archived with the domain, the role or its circle"""
        from django.utils import timezone

        from governance.proposals.instructions import adopt

        stays = Domain.objects.create(role=self.admin, text="Backups")
        access = Policy.objects.create(
            role=self.admin, domain=self.servers, title="Access"
        )
        restore = Policy.objects.create(role=self.admin, domain=stays, title="Restore")

        def governance(circle, *instructions):
            return adopt(
                Proposal.objects.create(
                    circle=circle,
                    proposer=self.ada,
                    tension="Changes",
                    created_at=timezone.now(),
                    instructions=list(instructions),
                )
            )

        # Moved into the sub-circle: the policies stay the role's, its
        # Role Leads still change them
        governance(
            self.web,
            {
                "op": "move",
                "path": f"/roles/{self.hosting.pk}/supporting_circle/roles/{self.admin.pk}",
                "from": f"/roles/{self.admin.pk}",
            },
        )
        access.refresh_from_db()
        self.assertEqual((access.role, access.archived_on), (self.admin, None))
        self.client.force_login(self.ada)
        self.assertEqual(
            self.client.get(
                f"/roles/{self.admin.pk}/domain-policies/{access.pk}/"
            ).status_code,
            200,
        )

        # The domain removed: its policies go, the other domain's stay
        proposal = governance(
            self.hosting,
            {
                "op": "remove",
                "path": f"/roles/{self.admin.pk}/domains/{self.servers.pk}",
                "original_value": "Server access",
            },
        )
        access.refresh_from_db()
        restore.refresh_from_db()
        self.assertIsNotNone(access.archived_on)
        self.assertIsNone(restore.archived_on)
        self.assertIn(access, proposal.policies.all())  # In the history

        # The role removed with its circle: its policies too
        governance(self.web, {"op": "remove", "path": f"/roles/{self.hosting.pk}"})
        restore.refresh_from_db()
        self.assertIsNotNone(restore.archived_on)
