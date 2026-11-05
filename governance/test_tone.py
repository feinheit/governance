from django.test import SimpleTestCase

from governance.templatetags.governance import tone


class ToneTest(SimpleTestCase):
    def test_tone(self):
        self.assertEqual(tone("published"), "wb-tone-warning")
        self.assertEqual(tone("objection"), "wb-tone-danger")
        self.assertEqual(tone("accountabilities-added"), "wb-tone-success")
        self.assertEqual(tone("policy-removed"), "wb-tone-neutral")
        self.assertEqual(tone("purpose"), "wb-tone-info")
        self.assertEqual(tone("governance"), "wb-tone-core")  # Meetings
