from django.contrib import admin
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from governance.accounts.models import APIToken, User
from governance.meetings.models import AgendaItem, Election, Meeting
from governance.proposals.models import Proposal, Response
from governance.roles.models import (
    Accountability,
    Assignment,
    ChecklistItem,
    Domain,
    Link,
    Metric,
    Policy,
    Role,
)


class AdminTest(TestCase):
    def test_all_models(self):
        """Every model is in the admin, its pages work"""
        ada = User.objects.create_superuser("ada@example.com", full_name="Ada")
        self.client.force_login(ada)
        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        cook = Role.objects.create(name="Cook", circle=kitchen)
        Accountability.objects.create(role=cook, text="Cooking")
        Domain.objects.create(role=cook, text="The fridge")
        Assignment.objects.create(role=cook, user=ada)
        Policy.objects.create(role=kitchen, title="Clean up")
        Metric.objects.create(role=cook, description="Soups")
        ChecklistItem.objects.create(role=cook, description="Stove off")
        Link.objects.create(role=cook, title="Tasks", url="https://example.com")
        APIToken.create_for(user=ada, title="gov", access="read")
        proposal = Proposal.objects.create(
            circle=kitchen, proposer=ada, tension="Soup", created_at=timezone.now()
        )
        Response.objects.create(proposal=proposal, user=ada, kind="comment")
        meeting = Meeting.objects.create(circle=kitchen, kind=Meeting.GOVERNANCE)
        AgendaItem.objects.create(meeting=meeting, position=1, label="Bread")
        Election.objects.create(
            meeting=meeting, role=cook, user=ada, term_ends_on=timezone.localdate()
        )

        for model, model_admin in admin.site._registry.items():
            opts = model._meta
            with self.subTest(model=opts.label):
                url = reverse(f"admin:{opts.app_label}_{opts.model_name}_changelist")
                self.assertEqual(self.client.get(url).status_code, 200)
                if model_admin.search_fields:
                    response = self.client.get(url, {"q": "a"})
                    self.assertEqual(response.status_code, 200)
                if model_admin.has_add_permission(self.client.request().wsgi_request):
                    add = reverse(f"admin:{opts.app_label}_{opts.model_name}_add")
                    self.assertEqual(self.client.get(add).status_code, 200)
                obj = model.objects.first()
                if obj is not None:
                    change = reverse(
                        f"admin:{opts.app_label}_{opts.model_name}_change",
                        args=[obj.pk],
                    )
                    self.assertEqual(self.client.get(change).status_code, 200)

        # All models of the project are registered
        from django.apps import apps

        ours = {m for m in apps.get_models() if m.__module__.startswith("governance.")}
        self.assertEqual(ours - set(admin.site._registry), set())


class DeactivateTest(TestCase):
    def test_deactivating_ends_the_assignments(self):
        """People leaving don't keep their roles; their proposals stay"""
        import datetime as dt

        from governance.roles.assignments import sync_circle_role_leads

        admin_user = User.objects.create_superuser("root@example.com")
        eve = User.objects.create_user("eve@example.com", full_name="Eve")
        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        kitchen.create_core_roles()
        cook = Role.objects.create(name="Cook", circle=kitchen)
        bakery = Role.objects.create(name="Bakery", is_circle=True, circle=kitchen)
        bakery.create_core_roles()
        since = dt.date(2026, 1, 1)
        Assignment.objects.create(role=cook, user=eve, starts_on=since)
        Assignment.objects.create(
            role=bakery.roles.get(core_role="lead"), user=eve, starts_on=since
        )
        sync_circle_role_leads(bakery, since)
        self.assertTrue(Assignment.objects.current().filter(role=bakery).exists())
        published = Proposal.objects.create(
            circle=kitchen,
            proposer=eve,
            tension="Soup",
            status=Proposal.PUBLISHED,
            created_at=timezone.now(),
        )

        self.client.force_login(admin_user)
        response = self.client.post(
            reverse("admin:accounts_user_change", args=[eve.pk]),
            {
                "email": eve.email,
                "full_name": eve.full_name,
                "short_name": "",
                "language": "",
                "notify_all": "",
                "is_admin": "",
                "glassfrog_id": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        eve.refresh_from_db()
        self.assertFalse(eve.is_active)
        self.assertFalse(Assignment.objects.current().filter(user=eve).exists())
        # Leading the bakery made her hold the bakery's role in the kitchen
        self.assertFalse(Assignment.objects.current().filter(role=bakery).exists())
        published.refresh_from_db()
        self.assertEqual(published.status, Proposal.PUBLISHED)
