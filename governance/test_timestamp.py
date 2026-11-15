import datetime as dt

from django.template import Context, Template
from django.test import SimpleTestCase, override_settings
from django.utils import translation


@override_settings(TIME_ZONE="Europe/Zurich")
class TimestampTest(SimpleTestCase):
    def render(self, value):
        with translation.override("en"):
            return Template("{% load governance %}{{ value|timestamp }}").render(
                Context({"value": value})
            )

    def test_moment(self):
        """The day, the exact time (local) when hovering it"""
        moment = dt.datetime(2026, 11, 5, 13, 30, tzinfo=dt.UTC)
        self.assertHTMLEqual(
            self.render(moment),
            '<time datetime="2026-11-05T14:30:00+01:00"'
            ' title="5 November 2026 14:30">05.11.2026</time>',
        )

    def test_day(self):
        self.assertEqual(self.render(dt.date(2026, 11, 5)), "05.11.2026")
        self.assertEqual(self.render(None), "")
