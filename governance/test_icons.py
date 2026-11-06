import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class IconsTest(SimpleTestCase):
    def test_icons_exist(self):
        """Every {% icon %} of the templates has its class in icons.css,
        which only lists the icons in use"""
        base = Path(settings.BASE_DIR)
        css = (base / "frontend" / "styles" / "icons.css").read_text()
        defined = set(re.findall(r"\.bi-([\w-]+)::before", css))
        used = {
            name
            for path in (base / "governance" / "templates").rglob("*.html")
            for name in re.findall(r'{% icon "([\w-]+)" %}', path.read_text())
        }
        self.assertTrue(used)
        self.assertEqual(used - defined, set())
        self.assertEqual(defined - used, set(), "Unused icons in icons.css")
