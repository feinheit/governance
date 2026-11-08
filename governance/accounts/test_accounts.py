from unittest import mock

from django.test import TestCase, override_settings

from governance.accounts.models import User
from governance.audit.models import LoggedAction


def mock_google():
    return mock.patch("governance.accounts.views.GoogleOAuth2Client")


class AccountsTest(TestCase):
    def oauth2(self, user_data, **kwargs):
        with mock_google() as client:
            client.return_value.get_user_data.return_value = user_data
            return self.client.get("/accounts/oauth2/?code=x", **kwargs)

    def test_login_required(self):
        response = self.client.get("/")
        self.assertRedirects(response, "/accounts/login/")

        response = self.client.get("/accounts/login/")
        self.assertContains(response, "/accounts/oauth2/")

    def test_redirect_to_google(self):
        with mock_google() as client:
            client.return_value.get_authentication_url.return_value = (
                "https://accounts.example.com/"
            )
            response = self.client.get("/accounts/oauth2/")
        self.assertRedirects(
            response, "https://accounts.example.com/", fetch_redirect_response=False
        )

    def test_existing_user(self):
        User.objects.create_user("ada@example.com")
        response = self.oauth2({"email": "ada@example.com"}, follow=True)
        self.assertEqual(response.wsgi_request.user.email, "ada@example.com")

    def test_next_after_login(self):
        User.objects.create_user("ada@example.com")
        self.client.get("/admin/")  # Sets the signed "next" cookie
        response = self.oauth2({"email": "ada@example.com"})
        self.assertRedirects(response, "/admin/", fetch_redirect_response=False)
        self.assertEqual(response.cookies["login_hint"].value, "ada@example.com")

    def test_inactive_user(self):
        User.objects.create_user("ada@example.com", is_active=False)
        response = self.oauth2({"email": "ada@example.com"}, follow=True)
        self.assertFalse(response.wsgi_request.user.is_authenticated)
        self.assertContains(response, "is inactive")

    def test_unknown_user(self):
        response = self.oauth2({"email": "ada@example.com"}, follow=True)
        self.assertFalse(response.wsgi_request.user.is_authenticated)
        self.assertContains(response, "No user with email address")

    def test_failing_google(self):
        with mock_google() as client:
            client.return_value.get_user_data.side_effect = ValueError
            response = self.client.get("/accounts/oauth2/?code=x", follow=True)
        self.assertContains(response, "Error while fetching user data")

    @override_settings(DEBUG=True)
    def test_force_login(self):
        User.objects.create_user("ada@example.com")
        response = self.client.get("/accounts/login/?force_login=ada@example.com")
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        response = self.client.get("/accounts/login/")
        self.assertRedirects(response, "/", fetch_redirect_response=False)

    def test_logout(self):
        self.client.force_login(User.objects.create_user("ada@example.com"))
        response = self.client.post("/accounts/logout/", follow=True)
        self.assertContains(response, "You have been signed out")
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_user(self):
        user = User(email="ada@example.com")
        self.assertEqual((str(user), user.get_short_name()), ("ada@example.com", "ada"))
        user = User(email="ada@example.com", full_name="Ada Example", short_name="AE")
        self.assertEqual(
            (user.get_full_name(), user.get_short_name()), ("Ada Example", "AE")
        )
        self.assertFalse(user.has_perm("x") or user.has_module_perms("x"))
        admin = User.objects.create_superuser("root@example.com")
        self.assertTrue(admin.is_staff and admin.has_perm("x"))
        self.assertEqual(list(User.objects.active()), [admin])


class AuditTest(TestCase):
    def test_changes_are_logged_with_the_user(self):
        user = User.objects.create_superuser("ada@example.com", short_name="ada")
        self.client.force_login(user)
        self.client.get("/")  # Sets the audit user name for this connection
        user.full_name = "Ada Example"
        user.save()
        action = LoggedAction.objects.for_instance(user).latest("event_id")
        self.assertEqual(action.action, "U")
        self.assertEqual(action.changed_fields, {"full_name": "Ada Example"})
        self.assertEqual(action.user_id, user.id)
        self.assertIn("UPDATE accounts_user", str(action))


class SettingsTest(TestCase):
    def test_settings(self):
        """Name, short name, language and mails in one form, from the own
        page and the menu; the mail address only shown: signing in uses it"""
        ada = User.objects.create_user("ada@example.com", full_name="Ada")
        bob = User.objects.create_user("bob@example.com", full_name="Bob")
        self.client.force_login(ada)
        response = self.client.get(ada.get_absolute_url())
        self.assertContains(response, 'href="/accounts/settings/"')
        self.assertContains(response, 'href="/accounts/settings/?next=/people/')
        self.assertNotContains(
            self.client.get(bob.get_absolute_url()), 'href="/accounts/settings/"'
        )
        response = self.client.get("/accounts/settings/")
        self.assertContains(response, 'value="ada@example.com"')
        self.assertContains(response, "disabled")

        data = {
            "email": "eve@example.com",
            "full_name": "Ada Lovelace",
            "short_name": "Ada L.",
            "language": "de",
            "notify_all": "True",
        }
        response = self.client.post("/accounts/settings/?next=/proposals/", data)
        self.assertRedirects(response, "/proposals/", fetch_redirect_response=False)
        ada.refresh_from_db()
        self.assertEqual(
            (ada.email, ada.full_name, ada.short_name, ada.language, ada.notify_all),
            ("ada@example.com", "Ada Lovelace", "Ada L.", "de", True),
        )
        # The message and the page in the new language
        response = self.client.get(ada.get_absolute_url())
        self.assertContains(response, "Einstellungen")
        self.assertContains(response, "gespeichert")

        # Only the app's languages, a name, no other sites
        response = self.client.post(
            "/accounts/settings/", data | {"language": "fr", "full_name": ""}
        )
        self.assertEqual(response.status_code, 200)
        ada.refresh_from_db()
        self.assertEqual((ada.language, ada.full_name), ("de", "Ada Lovelace"))
        response = self.client.post(
            "/accounts/settings/?next=https://example.com/", data | {"language": "en"}
        )
        self.assertRedirects(response, ada.get_absolute_url())
        # A language is required: without one pages follow the browser but
        # mails are German. Preselected: the page's
        self.client.post("/accounts/settings/", data | {"language": ""})
        ada.refresh_from_db()
        self.assertEqual(ada.language, "en")
        User.objects.filter(pk=ada.pk).update(language="")
        response = self.client.get(
            "/accounts/settings/", headers={"accept-language": "de"}
        )
        self.assertContains(response, '<option value="de" selected>')
