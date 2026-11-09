from django.test import TestCase

from governance.diff import diff
from governance.roles.models import Role


class DiffTest(TestCase):
    def test_words(self):
        self.assertHTMLEqual(
            diff("Tidy the kitchen daily.", "Tidy the kitchen weekly."),
            '<p>Tidy the kitchen <del class="wb-diff-del">daily</del>'
            '<ins class="wb-diff-ins">weekly</ins>.</p>',
        )

    def test_lists_stay_lists(self):
        html = diff(
            "Rules:\n\n- Knives\n- Forks\n- Spoons",
            "Rules:\n\n- Knives\n- Spoons\n- Plates",
        )
        self.assertHTMLEqual(
            html,
            "<p>Rules:</p><ul><li>Knives</li>"
            '<li><del class="wb-diff-del wb-diff-line">Forks</del></li>'
            "<li>Spoons</li>"
            '<li><ins class="wb-diff-ins wb-diff-line">Plates</ins></li></ul>',
        )
        # Words only: their list items stay as they are (the bullets of
        # whole lines are colored, main.css)
        self.assertHTMLEqual(
            diff("- Knives and forks", "- Knives and spoons"),
            '<ul><li>Knives and <del class="wb-diff-del">forks</del>'
            '<ins class="wb-diff-ins">spoons</ins></li></ul>',
        )

    def test_paragraphs(self):
        """A change spanning paragraphs is marked in each of them"""
        html = diff("One.\n\nTwo old.", "One new.\n\nTwo.")
        self.assertEqual(html.count("<p>"), 2)
        self.assertInHTML('<ins class="wb-diff-ins">new</ins>', html)
        self.assertInHTML('<del class="wb-diff-del">old</del>', html)

    def test_mentions(self):
        cook = Role.objects.create(name="Cook")
        html = diff(
            f"Asks @[Cook](role:{cook.pk}) first.",
            f"Asks @[Cook](role:{cook.pk}) always.",
        )
        self.assertIn(f'<a href="/roles/{cook.pk}/">@Cook</a>', html)
        self.assertInHTML('<del class="wb-diff-del">first</del>', html)

    def test_rewritten(self):
        """Little in common: removed and added as a whole"""
        html = diff("Lorem ipsum dolor.", "Something else entirely now.")
        self.assertInHTML(
            '<del class="wb-diff-del wb-diff-line">Lorem ipsum dolor.</del>', html
        )
        self.assertInHTML(
            '<ins class="wb-diff-ins wb-diff-line">Something else entirely now.</ins>',
            html,
        )

    def test_escaped(self):
        html = diff("<b>old</b>", "<b>new</b>")
        self.assertNotIn("<b>", html)
