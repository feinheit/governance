import re

from django.test import TestCase

from governance.accounts.models import User
from governance.help import PAGES


class HelpTest(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user("ada@example.com"))

    def test_pages(self):
        response = self.client.get("/help/")
        self.assertContains(response, "<h1>Hilfe</h1>", html=True)
        self.assertContains(response, 'href="/help/vorschlaege/"')
        self.assertContains(response, 'href="/help/"')  # In the navigation
        for page in PAGES:
            with self.subTest(page=page):
                url = f"/help/{page}/" if page else "/help/"
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                # The docs link each other, every link leads to a help page
                self.assertEqual(
                    re.findall(r'href="[^"]*\.md', response.content.decode()), []
                )
        self.assertContains(
            self.client.get("/help/verfassung/"), "Holacracy Verfassung"
        )
        self.assertEqual(self.client.get("/help/missing/").status_code, 404)
