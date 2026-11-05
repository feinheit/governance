"""End-to-end tests of meetings in a browser (htmx)

They run the real server (``LiveServerTestCase``, serving ``static/``
with the production bundle ``./runtests.sh`` builds) and Chromium through
Playwright, installed with ``uv run playwright install chromium``. Without
the browser or the bundle they're skipped; ``./runtests.sh --exclude-tag
e2e`` leaves them out, CI runs them.
"""

import os

from django.conf import settings
from django.test import Client, LiveServerTestCase, tag
from django.urls import reverse
from django.utils import timezone

from governance.accounts.models import User
from governance.meetings.models import AgendaItem, Meeting
from governance.proposals.models import Proposal
from governance.roles.models import Assignment, Role


try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None


@tag("e2e")
class MeetingE2ETest(LiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        if sync_playwright is None:  # pragma: no cover
            raise cls.skipTest(cls, "Playwright isn't installed")
        if not (settings.STATIC_ROOT / "main.html").exists():  # pragma: no cover
            raise cls.skipTest(cls, "No bundle: yarn rspack build --mode production")
        # Playwright's sync API runs an event loop, the test's database
        # access happens outside of it
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
        super().setUpClass()
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch()
        except Exception as exc:  # pragma: no cover
            cls.playwright.stop()
            super().tearDownClass()
            raise cls.skipTest(cls, f"No browser: {exc}") from exc

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        super().tearDownClass()
        os.environ.pop("DJANGO_ALLOW_ASYNC_UNSAFE", None)

    def setUp(self):
        self.ada = User.objects.create_user(
            "ada@example.com", full_name="Ada", language="en"
        )
        self.kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        self.kitchen.create_core_roles()
        self.cook = Role.objects.create(name="Cook", circle=self.kitchen)
        Assignment.objects.create(role=self.cook, user=self.ada)
        self.meeting = Meeting.objects.create(
            circle=self.kitchen,
            kind=Meeting.GOVERNANCE,
            started_at=timezone.now(),
            facilitator=self.ada,
            secretary=self.ada,
        )
        self.meeting.attendees.add(self.ada)

        client = Client()
        client.force_login(self.ada)
        self.context = self.browser.new_context()
        self.context.add_cookies([
            {
                "name": "sessionid",
                "value": client.cookies["sessionid"].value,
                "url": self.live_server_url,
            }
        ])
        self.page = self.context.new_page()
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.on(
            "console",
            lambda message: (
                message.type == "error" and self.errors.append(message.text)
            ),
        )

    def tearDown(self):
        self.context.close()

    def assertSamePage(self):
        """Actions replace the meeting's region, the page isn't reloaded"""
        self.assertEqual(self.page.evaluate("window.marker"), 1)

    def test_meeting(self):
        page = self.page
        page.goto(f"{self.live_server_url}{self.meeting.get_absolute_url()}")
        page.evaluate("window.marker = 1")

        # Building the agenda and processing an item
        page.fill("input[name=label]", "Bread")
        page.locator("form[action$='/agenda/add/'] button[type=submit]").first.click()
        page.wait_for_selector("#agenda >> text=Bread")
        self.assertEqual(page.input_value("input[name=label]"), "")
        page.locator("#agenda form[action$='/process/'] button").click()
        page.locator("form[action$='/proposal/'] button").click()
        page.wait_for_selector(".wb-amend-area")
        self.assertSamePage()

        # The secretary amends the proposal in the panel
        add_role = page.locator(".wb-amend-area a[href*='/roles/new/']")
        add_role.click()
        page.wait_for_selector("#amend form")
        # Without a name: the browser's validation keeps the form open
        page.locator("#amend button[type=submit]").click()
        self.assertEqual(page.locator("#amend input[name=name]:invalid").count(), 1)
        page.fill("#amend input[name=name]", "Baker")
        page.locator("#amend button[type=submit]").click()
        page.wait_for_selector("#meeting >> text=Baker")
        self.assertEqual(page.locator("#amend > *").count(), 0)
        self.assertSamePage()

        # Cancelling closes the panel, undoing drops the change
        add_role.click()
        page.wait_for_selector("#amend form")
        page.locator("#amend a[data-in-meeting]").click()
        page.wait_for_selector("#amend form", state="detached")
        page.locator("form[action*='/undo/'] button").click()
        page.wait_for_selector("#meeting >> text=Baker", state="detached")
        add_role.click()
        page.fill("#amend input[name=name]", "Baker")
        page.locator("#amend button[type=submit]").click()
        page.wait_for_selector("#meeting >> text=Baker")
        self.assertSamePage()

        # Adopting changes the governance right away
        page.locator("form[action$='/adopt/'] button").click()
        page.wait_for_selector("#meeting .wb-amend-area", state="detached")
        self.assertTrue(Role.objects.filter(circle=self.kitchen, name="Baker").exists())
        self.assertEqual(Proposal.objects.get().status, Proposal.ADOPTED)
        self.assertSamePage()

        # Others' changes appear by themselves
        AgendaItem.objects.create(
            meeting=self.meeting, label="From another device", position=9
        )
        page.evaluate("document.activeElement?.blur()")
        page.wait_for_selector("#agenda >> text=From another device", timeout=8000)
        self.assertSamePage()

        # Ending the meeting shows its outputs
        page.locator("form[action$='/end/'] button").click()
        page.wait_for_selector("#meeting >> text=Outputs")
        self.assertEqual(page.locator("#meeting >> text=Baker").count() > 0, True)
        self.assertSamePage()

        # Links to other pages navigate as usual
        page.locator(
            f"#meeting a[href='{self.kitchen.get_absolute_url()}']"
        ).first.click()
        page.wait_for_url(f"**{self.kitchen.get_absolute_url()}")
        self.assertIsNone(page.evaluate("window.marker"))
        self.assertEqual(self.errors, [])

    def test_mentions(self):
        """The list of roles opens below the "@" being typed (mentions.js),
        e.g. in the forms amending a proposal in the meeting"""
        Assignment.objects.create(
            role=self.kitchen.roles.get(core_role="lead"), user=self.ada
        )
        page = self.page
        page.goto(f"{self.live_server_url}/roles/{self.kitchen.pk}/strategy/")
        textarea = page.locator("textarea[data-mentions]")
        textarea.fill("")
        textarea.press_sequentially("First line\nSecond line with @Co")
        page.wait_for_selector(".wb-mentions:not([hidden])")

        area = textarea.bounding_box()
        mentions = page.locator(".wb-mentions").bounding_box()
        # Below the second line, inside the textarea, not at its left edge
        self.assertLess(mentions["y"], area["y"] + area["height"])
        self.assertGreater(mentions["y"], area["y"] + 20)
        self.assertGreater(mentions["x"], area["x"] + 50)

        textarea.press("Enter")
        self.assertIn(f"with @[Cook](role:{self.cook.pk}) ", textarea.input_value())
        self.assertEqual(self.errors, [])

    def test_circle_browser(self):
        """The circle browser (Preact and d3) is loaded only on its page"""
        page = self.page
        scripts = []
        page.on(
            "request",
            lambda request: (
                request.resource_type == "script" and scripts.append(request.url)
            ),
        )
        page.goto(f"{self.live_server_url}{self.kitchen.get_absolute_url()}")
        page.wait_for_load_state("networkidle")
        self.assertEqual([url for url in scripts if "/circles." in url], [])

        page.goto(f"{self.live_server_url}{reverse('circle_browser')}")
        page.wait_for_selector("#circle-browser .cb-label >> text=Cook")
        self.assertIsNone(page.locator("#circle-list").get_attribute("open"))
        self.assertEqual(len([url for url in scripts if "/circles." in url]), 1)

        # Hovering a role shows its holders next to the mouse, the labels
        # are shortened
        box = page.locator('circle.cb-node[aria-label="Cook"]').bounding_box()
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        page.mouse.move(x, y)
        tooltip = page.locator(".cb-tooltip")
        self.assertIn("Ada", tooltip.inner_text())
        position = tooltip.bounding_box()
        self.assertLess(abs(position["x"] - x), 40)
        self.assertLess(abs(position["y"] - y), 40)

        # Choosing one of my roles highlights it
        page.get_by_role("button", name="My roles").click()
        page.locator(".cb-mine-list .btn", has_text="Cook").click()
        page.wait_for_selector('circle.cb-highlight[aria-label="Cook"]')
        self.assertEqual(self.errors, [])

    def test_shortcuts(self):
        """Alt with a letter: the search field, the start page, the
        organization"""
        page = self.page
        page.goto(f"{self.live_server_url}{self.cook.get_absolute_url()}")
        page.keyboard.press("Alt+q")
        self.assertEqual(page.evaluate("document.activeElement.name"), "q")
        page.keyboard.press("Alt+h")
        page.wait_for_url(f"**{self.kitchen.get_absolute_url()}")  # The start
        page.goto(f"{self.live_server_url}{self.cook.get_absolute_url()}")
        page.keyboard.press("Alt+o")
        page.wait_for_url(f"**{self.kitchen.get_absolute_url()}")
        self.assertEqual(
            page.get_attribute("[data-shortcut=o]", "aria-keyshortcuts"), "Alt+O"
        )
        self.assertEqual(self.errors, [])
