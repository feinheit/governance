import re

from django.test import TestCase

from governance.accounts.models import User
from governance.help import PAGES


class HelpTest(TestCase):
    def setUp(self):
        self.client.force_login(
            User.objects.create_user("ada@example.com", language="de")
        )

    def test_pages(self):
        response = self.client.get("/help/")
        self.assertContains(response, "<h1>Hilfe</h1>", html=True)
        self.assertContains(response, 'href="/help/proposals/"')
        self.assertContains(response, 'href="/help/"')  # In the navigation
        for page in PAGES["de"]:
            with self.subTest(page=page):
                url = f"/help/{page}/" if page else "/help/"
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                # The docs link each other, every link leads to a help page
                self.assertEqual(
                    re.findall(r'href="[^"]*\.md', response.content.decode()), []
                )
        self.assertContains(
            self.client.get("/help/constitution/"), "Holacracy Verfassung"
        )
        self.assertEqual(self.client.get("/help/missing/").status_code, 404)

    def test_html(self):
        """The docs are ours, HTML like the keys of the shortcuts works"""
        response = self.client.get("/help/orientation/")
        self.assertContains(response, "<kbd>Alt-H</kbd>")

    def test_english(self):
        """The same pages in English, the constitution's English original"""
        self.client.force_login(
            User.objects.create_user("bob@example.com", language="en")
        )
        response = self.client.get("/help/")
        self.assertContains(response, "<h1>Help</h1>", html=True)
        self.assertContains(response, 'href="/help/proposals/"')
        self.assertContains(response, 'href="/help/constitution/"')
        for page in PAGES["en"]:
            with self.subTest(page=page):
                url = f"/help/{page}/" if page else "/help/"
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    re.findall(r'href="[^"]*\.md', response.content.decode()), []
                )
                # No German page left untranslated
                self.assertNotContains(response, " und ")
        self.assertContains(
            self.client.get("/help/constitution/"), "Holacracy Constitution"
        )
