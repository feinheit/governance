from django.test import SimpleTestCase
from django.utils import translation

from governance.proposals.describe import describe, summarize


class SummaryTest(SimpleTestCase):
    @translation.override("en")
    def test_summary(self):
        """One line per role or policy: added, changed, removed or moved"""
        instructions = [
            {"op": "add", "path": "/roles/n1"},
            {"op": "add", "path": "/roles/n1/name", "value": "Baker"},
            {"op": "add", "path": "/roles/n1/aim", "value": "Bread"},
            {
                "op": "replace",
                "path": "/roles/2/name",
                "original_value": "Cook",
                "value": "Chef",
            },
            {
                "op": "add",
                "path": "/roles/2/accountabilities/n2",
                "value": "Soups",
            },
            {"op": "remove", "path": "/policies/3"},
            {"op": "add", "path": "/roles/4/supporting_circle/roles/5"},
        ]
        names = {
            "roles/2": "Cook",
            "policies/3": "Tea",
            "roles/4": "Bakery",
            "roles/5": "Pastry",
        }
        self.assertEqual(
            [
                (s.action, s.kind, s.name, s.target)
                for s in summarize(describe(instructions, names))
            ],
            [
                ("added", "Role", "Baker", ""),
                ("changed", "Role", "Cook", ""),
                ("removed", "Policy", "Tea", ""),
                ("moved", "Role", "Pastry", "Bakery"),
            ],
        )
