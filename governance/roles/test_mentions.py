import datetime as dt

from django.test import TestCase

from governance.roles.mentions import MentionResolver, render_mentions
from governance.roles.models import Role
from governance.templatetags.governance import markdown


class MentionsTest(TestCase):
    def test_convert_and_render(self):
        anchor = Role.objects.create(name="Example Ltd", is_circle=True)
        kitchen = Role.objects.create(name="Kitchen", is_circle=True, circle=anchor)
        other = Role.objects.create(name="Hall", is_circle=True, circle=anchor)
        coordinator = Role.objects.create(
            name="Coordinator:in intern", circle=kitchen, glassfrog_id=55
        )
        short = Role.objects.create(name="Coordinator:in", circle=other)
        cook = Role.objects.create(name="Cook", circle=kitchen)
        hall_cook = Role.objects.create(name="Cook", circle=other)
        gone = Role.objects.create(
            name="Taster", circle=kitchen, archived_on=dt.date(2026, 1, 1)
        )
        renamed = Role.objects.create(name="Head Chef", circle=kitchen)

        resolver = MentionResolver(
            Role.objects.all(), {renamed.pk: ["Chef de cuisine"]}
        )
        convert = resolver.convert
        # The longest name wins, names end at a word boundary
        self.assertEqual(
            convert("Ask @Coordinator:in intern now", kitchen),
            f"Ask @[Coordinator:in intern](role:{coordinator.pk}) now",
        )
        self.assertEqual(
            convert("Ask @Coordinator:in!", kitchen),
            f"Ask @[Coordinator:in](role:{short.pk})!",
        )
        # Underscores, the circle's own roles first, earlier names, archived roles
        self.assertEqual(
            convert("@Coordinator:in_intern", kitchen),
            f"@[Coordinator:in intern](role:{coordinator.pk})",
        )
        self.assertEqual(convert("@Cook", kitchen), f"@[Cook](role:{cook.pk})")
        self.assertEqual(convert("@Cook", other), f"@[Cook](role:{hall_cook.pk})")
        self.assertEqual(
            convert("@Chef de cuisine", kitchen), f"@[Head Chef](role:{renamed.pk})"
        )
        self.assertEqual(convert("@Taster", kitchen), f"@[Taster](role:{gone.pk})")
        # Pasted GlassFrog links
        self.assertEqual(
            convert(
                "[@Old name](https://app.glassfrog.com/organizations/1/orgnav/roles/55)"
            ),
            f"@[Coordinator:in intern](role:{coordinator.pk})",
        )
        # Not mentions, already converted, unknown
        self.assertEqual(convert("mail@example.com"), "mail@example.com")
        self.assertEqual(
            convert(f"@[Cook](role:{cook.pk})"), f"@[Cook](role:{cook.pk})"
        )
        self.assertEqual(convert("@Nobody here"), "@Nobody here")
        self.assertEqual(resolver.unresolved, ["Nobody here"])
        self.assertEqual(convert(""), "")

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
