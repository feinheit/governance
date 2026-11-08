import importlib.util
from pathlib import Path

from django.test import SimpleTestCase


spec = importlib.util.spec_from_file_location(
    "handbook_links",
    Path(__file__).parent.parent / "scripts" / "handbook_links.py",
)
handbook_links = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handbook_links)

ORG = "https://app.glassfrog.com/organizations/1/orgnav"
OBJECTS = {
    "roles": {
        11: {"id": 3, "name": "Cook", "archived_on": None},
        12: {"id": 4, "name": "Baker", "archived_on": "2026-01-02"},
    },
    "policies": {21: {"id": 7, "title": "Fridge", "archived_on": None}},
}


class HandbookLinksTest(SimpleTestCase):
    def test_rewrite(self):
        text = f"""\
The `Cook <{ORG}/roles/11/overview>`__ and the `Chef
<https://de.glassfrog.com/organizations/1/orgnav/roles/11/>`__.

Our `Policy
Fridge <{ORG}/policies/21>`__, see [the baker]({ORG}/roles/12).
Everything in `GlassFrog <{ORG}>`__, but not `this <{ORG}/roles/99>`__.
"""
        new, notes = handbook_links.rewrite(text, OBJECTS, "https://gov.example/")
        self.assertEqual(
            new,
            """\
The `Cook <https://gov.example/roles/3/>`__ and the `Chef
<https://gov.example/roles/3/>`__.

Our `Policy
Fridge <https://gov.example/policies/7/>`__, see [the baker](https://gov.example/roles/4/).
"""
            f"Everything in `GlassFrog <https://gov.example/>`__, but not `this <{ORG}/roles/99>`__.\n",
        )
        self.assertEqual(
            notes,
            [
                (2, "link text 'Chef', now called 'Cook'"),
                (5, "archived on 2026-01-02: Baker"),
                (6, f"unknown: {ORG}/roles/99"),
            ],
        )
