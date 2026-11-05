import datetime as dt

from django.test import SimpleTestCase
from django.utils import formats, translation


class FormatsTest(SimpleTestCase):
    def test_english_dates_like_german(self):
        """No m/d/Y and a.m./p.m. in English"""
        day = dt.date(2026, 11, 5)
        moment = dt.datetime(2026, 11, 5, 14, 30)
        with translation.override("en"):
            self.assertEqual(
                formats.date_format(day, "SHORT_DATE_FORMAT"), "05.11.2026"
            )
            self.assertEqual(
                formats.date_format(moment, "SHORT_DATETIME_FORMAT"), "05.11.2026 14:30"
            )
            self.assertEqual(formats.date_format(day), "5 November 2026")
