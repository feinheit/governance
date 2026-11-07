from django.test import TestCase

from governance.roles.mentions import render_mentions
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
