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

    def test_holders_change_policies(self):
        self.client.force_login(self.ada)
        response = self.client.get(f"/roles/{self.admin.pk}/")
        self.assertContains(response, "Add a policy for its domains")
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
        self.assertEqual((policy.role, policy.domain), (self.admin, self.servers))
        proposal = Proposal.objects.get()
        self.assertEqual(
            (
                proposal.kind,
                proposal.status,
                proposal.circle,
                proposal.role,
                proposal.proposer,
            ),
            (Proposal.DOMAIN_POLICY, Proposal.ADOPTED, self.web, self.admin, self.ada),
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

        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                f"/roles/{self.admin.pk}/domain-policies/{policy.pk}/remove/"
            )
        policy.refresh_from_db()
        self.assertIsNotNone(policy.archived_on)
        self.assertEqual(Proposal.objects.latest("pk").instructions[0]["op"], "remove")

    def test_permissions(self):
        circle_policy = Policy.objects.create(role=self.web, title="Tea")
        # Others don't, not the circle's policies, not roles without domains
        self.client.force_login(self.bob)
        self.assertNotContains(
            self.client.get(f"/roles/{self.admin.pk}/"), "Add a policy for its domains"
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
