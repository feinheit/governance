from django.test import TestCase
from django.utils import timezone

from governance.accounts.models import User
from governance.proposals.models import Proposal
from governance.roles.models import Assignment, Role


class NotFoundTest(TestCase):
    def setUp(self):
        self.ada = User.objects.create_user("ada@example.com", language="en")
        self.bob = User.objects.create_user("bob@example.com", language="en")
        self.kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        cook = Role.objects.create(name="Cook", circle=self.kitchen)
        Assignment.objects.create(role=cook, user=self.ada)
        self.draft = Proposal.objects.create(
            circle=self.kitchen,
            role=cook,
            proposer=self.ada,
            tension="No **bread**",
            created_at=timezone.now(),
        )

    def test_page(self):
        self.client.force_login(self.bob)
        response = self.client.get("/proposals/999999/")
        self.assertContains(response, "Page not found", status_code=404)
        self.assertContains(response, 'action="/search/"', status_code=404)
        # Somebody else's draft looks like a page which doesn't exist
        response = self.client.get(self.draft.get_absolute_url())
        self.assertContains(response, "or you don't have access", status_code=404)

    def test_deleted_draft(self):
        """Proposers learn that they deleted the draft, nobody else"""
        url = self.draft.get_absolute_url()
        self.client.force_login(self.ada)
        self.client.post(f"{url}delete/")
        self.assertFalse(Proposal.objects.exists())
        response = self.client.get(url)
        self.assertContains(response, "You deleted this draft on", status_code=404)
        self.assertContains(response, "<strong>bread</strong>", status_code=404)

        self.client.force_login(self.bob)
        response = self.client.get(url)
        self.assertNotContains(response, "bread", status_code=404)
