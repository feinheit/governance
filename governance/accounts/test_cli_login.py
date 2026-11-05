from django.conf import settings
from django.test import TestCase

from governance.accounts.models import APIToken, User
from governance.roles.models import Assignment, Role


class CLILoginTest(TestCase):
    def test_cli_login(self):
        """gov is authorized through the browser, after signing in"""
        url = "/cli-login/?port=8123&state=abcdefghijklmnop&name=laptop&access=read"
        self.assertRedirects(
            self.client.get(url), "/accounts/login/", fetch_redirect_response=False
        )

        user = User.objects.create_user("ada@example.com", language="en")
        self.client.force_login(user)
        response = self.client.get(url)
        self.assertContains(response, "laptop")
        self.assertContains(response, "read only")
        for invalid in [
            "/cli-login/",
            # gov has to ask for an access explicitly
            "/cli-login/?port=8123&state=abcdefghijklmnop",
            "/cli-login/?port=8123&state=abcdefghijklmnop&access=all",
            "/cli-login/?port=80&state=abcdefghijklmnop&access=read",
            "/cli-login/?port=8123&state=short&access=read",
            "/cli-login/?port=8123&state=abcdefghijklmnop%22&access=read",
        ]:
            with self.subTest(url=invalid):
                self.assertEqual(self.client.get(invalid).status_code, 400)

        response = self.client.post(url)
        token = user.api_tokens.get()
        self.assertEqual((token.title, token.access), ("gov (laptop)", "read"))
        self.assertContains(response, 'action="http://127.0.0.1:8123/"')
        self.assertContains(response, 'value="abcdefghijklmnop"')
        secret = (
            response.content.decode().split('name="token" value="')[1].split('"')[0]
        )
        self.assertEqual(APIToken.objects.for_secret(secret).user, user)

    def test_me(self):
        user = User.objects.create_user("ada@example.com", full_name="Ada")
        anchor = Role.objects.create(name="Zoo", is_circle=True)
        kitchen = Role.objects.create(name="Kitchen", is_circle=True, circle=anchor)
        cook = Role.objects.create(name="Cook", circle=kitchen)
        Assignment.objects.create(role=cook, user=user, focus="Soup")
        # The anchor comes first although "Zoo" comes after "Kitchen"
        keeper = Role.objects.create(name="Keeper", circle=anchor)
        Assignment.objects.create(role=keeper, user=user)
        _token, secret = APIToken.create_for(user=user, title="gov", access="read")
        data = self.client.get(
            "/api/me/", headers={"authorization": f"Bearer {secret}"}
        ).json()
        self.assertEqual((data["name"], data["access"]), ("Ada", "read"))
        self.assertEqual(data["roles"][0]["name"], "Keeper")
        self.assertEqual(
            data["roles"][1:],
            [
                {
                    "id": cook.pk,
                    "name": "Cook",
                    "circle_id": kitchen.pk,
                    "circle": "Kitchen",
                    "focus": "Soup",
                    "url": f"{settings.BASE_URL}/roles/{cook.pk}/",
                }
            ],
        )
