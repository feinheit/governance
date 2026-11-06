from django.test import TestCase

from governance.accounts.models import User
from governance.roles.models import Assignment, Metric, Role


MODAL = {"HTTP_HX_REQUEST": "true", "HTTP_HX_MODAL": "true"}


class ModalTest(TestCase):
    def setUp(self):
        self.ada = User.objects.create_user("ada@example.com", full_name="Ada")
        self.kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        self.kitchen.create_core_roles()
        Assignment.objects.create(
            role=self.kitchen.roles.get(core_role="lead"), user=self.ada
        )
        self.url = f"/roles/{self.kitchen.pk}/metrics/new/"

    def test_links(self):
        self.client.force_login(self.ada)
        self.assertContains(
            self.client.get(f"/roles/{self.kitchen.pk}/"),
            f'href="{self.url}" data-modal',
        )

    def test_form(self):
        """Only the form, posting to the modal, cancelling closes it"""
        self.client.force_login(self.ada)
        response = self.client.get(self.url, **MODAL)
        self.assertNotContains(response, "<html")
        self.assertContains(response, f'hx-post="{self.url}"')
        self.assertContains(response, 'id="modal-title"')
        self.assertContains(response, "data-modal-close")

        # The page without the header
        response = self.client.get(self.url)
        self.assertContains(response, "<html")
        self.assertNotContains(response, "hx-post")

    def test_errors_stay(self):
        self.client.force_login(self.ada)
        response = self.client.post(self.url, {"description": ""}, **MODAL)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "<html")
        self.assertContains(response, "This field is required.")
        self.assertFalse(Metric.objects.exists())

    def test_saving_loads_the_page(self):
        """Redirects become HX-Redirect: fetch would follow them itself"""
        self.client.force_login(self.ada)
        response = self.client.post(
            self.url, {"description": "Soups per week", "frequency": "weekly"}, **MODAL
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["HX-Redirect"], f"/roles/{self.kitchen.pk}/")
        self.assertTrue(Metric.objects.exists())

        # Without the header as before
        response = self.client.post(self.url, {"description": "Soups served"})
        self.assertRedirects(response, f"/roles/{self.kitchen.pk}/")

    def test_login(self):
        """Signed out (e.g. the session expired) the page shows the login"""
        response = self.client.get(self.url, **MODAL)
        self.assertEqual(response["HX-Redirect"], "/accounts/login/")
