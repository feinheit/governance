from django.test import TestCase

from governance.roles.mentions import link_mentions, render_mentions
from governance.roles.models import Role
from governance.templatetags.governance import markdown


class MentionsTest(TestCase):
    def test_render(self):
        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        cook = Role.objects.create(name="Cook", circle=kitchen)
        cook.name = "Chef"
        cook.save()
        self.assertEqual(
            render_mentions(f"Hi @[Cook](role:{cook.pk})"),
            f"Hi [@Chef](/roles/{cook.pk}/)",
        )
        self.assertEqual(render_mentions("@[Cook](role:999999)"), "@Cook")
        self.assertIn(
            f'<a href="/roles/{cook.pk}/">@Chef</a>',
            markdown(f"@[Cook](role:{cook.pk})"),
        )

    def test_link_plain_mentions(self):
        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        cook = Role.objects.create(name="Cook", circle=kitchen)
        head_cook = Role.objects.create(name="Head Cook", circle=kitchen)
        Role.objects.create(name="Facilitator", circle=kitchen)
        bar = Role.objects.create(name="Bar", is_circle=True)
        Role.objects.create(name="Facilitator", circle=bar)
        Role.objects.create(name="Waiter", circle=bar, archived_on="2026-01-01")
        self.assertEqual(
            link_mentions("Ask @cook, @Head Cook or @Cooks."),
            f"Ask @[Cook](role:{cook.pk}), @[Head Cook](role:{head_cook.pk})"
            " or @Cooks.",
        )
        # Ambiguous or archived, mail addresses and existing mentions
        for text in [
            "@Facilitator",
            "@Waiter",
            "cook@Kitchen.example",
            f"@[Cook](role:{cook.pk})",
            "[@Cook](https://example.com/)",
            "",
        ]:
            with self.subTest(text=text):
                self.assertEqual(link_mentions(text), text)
