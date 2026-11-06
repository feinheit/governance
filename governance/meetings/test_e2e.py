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
from governance.roles.models import Assignment, ChecklistItem, Policy, Role


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

    def test_remove_circle(self):
        """Moving out of a circle and removing it, in the meeting's panel"""
        bakery = Role.objects.create(name="Bakery", circle=self.kitchen, is_circle=True)
        bakery.create_core_roles()
        baker = Role.objects.create(name="Baker", circle=bakery)
        cleaner = Role.objects.create(name="Cleaner", circle=bakery)
        noise = Policy.objects.create(role=bakery, title="Noise")
        proposal = Proposal.objects.create(
            circle=self.kitchen,
            proposer=self.ada,
            role=self.cook,
            tension="No more bakery",
            status=Proposal.IN_MEETING,
            meeting=self.meeting,
            created_at=timezone.now(),
        )
        AgendaItem.objects.create(
            meeting=self.meeting, proposal=proposal, label="No more bakery"
        )
        page = self.page
        page.goto(f"{self.live_server_url}{self.meeting.get_absolute_url()}")
        page.evaluate("window.marker = 1")
        page.locator("#agenda form[action$='/process/'] button").click()
        page.wait_for_selector(".wb-amend-area")

        # Moving the policy out of the bakery
        page.locator(".wb-amend-area a[href*='/move/']").click()
        page.locator("#amend li", has_text="Noise").locator("button").click()
        page.wait_for_selector("#amend form", state="detached")
        self.assertIn(
            "from Bakery", page.locator("#meeting ul.list-unstyled").inner_text()
        )

        # Removing the bakery: the policy moves out already, Baker too
        page.locator(".wb-amend-area summary", has_text="role").click()
        page.locator(".wb-amend-area a[href*='/remove-circle/']").click()
        page.wait_for_selector("#amend form")
        self.assertTrue(
            page.is_checked(f"#amend input[name=policies][value='{noise.pk}']")
        )
        page.check(f"#amend input[name=roles][value='{baker.pk}']")
        page.locator("#amend button[type=submit]").click()
        page.wait_for_selector("#amend form", state="detached")
        self.assertSamePage()

        page.locator("form[action$='/adopt/'] button").click()
        page.wait_for_selector("#meeting .wb-amend-area", state="detached")
        for obj in [bakery, baker, cleaner, noise]:
            obj.refresh_from_db()
        self.assertEqual((baker.circle, baker.archived_on), (self.kitchen, None))
        self.assertEqual((noise.role, noise.archived_on), (self.kitchen, None))
        self.assertIsNotNone(bakery.archived_on)
        self.assertIsNotNone(cleaner.archived_on)
        self.assertSamePage()
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

    def test_modals(self):
        """Forms open in a modal (modal.js), Escape keeps changed ones open
        until pressed again, saving loads the page"""
        page = self.page
        page.goto(f"{self.live_server_url}{self.cook.get_absolute_url()}")
        add = page.locator("a[data-modal][href$='/checklist/new/']")
        add.click()
        page.wait_for_selector("#modal[open] textarea[name=description]:focus")
        page.keyboard.type("Sharpen the knives")
        page.keyboard.press("Escape")
        self.assertEqual(page.locator("#modal[open]").count(), 1)
        page.keyboard.press("Escape")
        page.wait_for_selector("#modal[open]", state="detached")

        add.click()
        page.fill("#modal textarea[name=description]", "Sharpen the knives")
        page.locator("#modal button[type=submit]").click()
        page.wait_for_selector("main >> text=Sharpen the knives")
        self.assertEqual(page.locator("#modal[open]").count(), 0)
        self.assertEqual(ChecklistItem.objects.get().description, "Sharpen the knives")

        # In a meeting its updates continue behind the modal
        page.goto(f"{self.live_server_url}{self.meeting.get_absolute_url()}")
        page.locator("a[data-modal][href$='/edit/']").click()
        page.fill("#modal[open] textarea[name=minutes]", "Short and sweet")
        AgendaItem.objects.create(meeting=self.meeting, label="Meanwhile", position=9)
        page.wait_for_selector("#agenda >> text=Meanwhile", timeout=8000)
        self.assertEqual(
            page.input_value("#modal textarea[name=minutes]"), "Short and sweet"
        )
        page.locator("#modal button[type=submit]").click()
        page.wait_for_selector("#meeting >> text=Short and sweet")
        self.assertEqual(self.errors, [])

    def test_holders(self):
        """Assigning and removing on the role's page, in modals"""
        Assignment.objects.create(
            role=self.kitchen.roles.get(core_role="lead"), user=self.ada
        )
        bob = User.objects.create_user("bob@example.com", full_name="Bob")
        page = self.page
        page.goto(f"{self.live_server_url}{self.cook.get_absolute_url()}")
        page.locator("a[data-modal]", has_text="Assign somebody").click()
        page.select_option("#modal[open] select[name=user]", str(bob.pk))
        page.fill("#modal input[name=focus]", "Bread")
        page.locator("#modal button[type=submit]").click()
        page.wait_for_selector("main >> text=Bread")
        self.assertTrue(Assignment.objects.filter(role=self.cook, user=bob).exists())

        page.locator(
            f"a[data-modal][href*='/assignments/{Assignment.objects.get(user=bob).pk}/end/']"
        ).click()
        page.wait_for_selector("#modal[open] >> text=Remove Bob from Cook?")
        page.locator("#modal button[type=submit]").click()
        page.wait_for_selector("main >> text=Bread", state="detached")
        self.assertFalse(Assignment.objects.filter(role=self.cook, user=bob).exists())
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
        """Alt with a letter: the search field, the start page (the own
        page), the organization"""
        page = self.page
        page.goto(f"{self.live_server_url}{self.cook.get_absolute_url()}")
        page.keyboard.press("Alt+q")
        self.assertEqual(page.evaluate("document.activeElement.name"), "q")
        page.keyboard.press("Alt+h")
        page.wait_for_url(f"**{self.ada.get_absolute_url()}")  # The start
        page.goto(f"{self.live_server_url}{self.cook.get_absolute_url()}")
        page.keyboard.press("Alt+o")
        page.wait_for_url(f"**{self.kitchen.get_absolute_url()}")
        self.assertEqual(
            page.get_attribute("[data-shortcut=o]", "aria-keyshortcuts"), "Alt+O"
        )
        self.assertEqual(self.errors, [])

    def test_rows_clickable(self):
        """Lists of roles, proposals etc.: the whole row opens the title's
        page, the other links in the row still work"""
        page = self.page
        page.goto(f"{self.live_server_url}{self.kitchen.get_absolute_url()}")
        row = page.locator(
            "li.wb-row-link", has=page.locator("a.wb-row-title", has_text="Cook")
        ).first
        row.scroll_into_view_if_needed()
        box = row.bounding_box()
        page.mouse.click(box["x"] + box["width"] - 20, box["y"] + box["height"] / 2)
        page.wait_for_url(f"**{self.cook.get_absolute_url()}")

        page.go_back()
        row.locator("a", has_text="Ada").first.click()
        page.wait_for_url(f"**{self.ada.get_absolute_url()}")
        self.assertEqual(self.errors, [])

    def test_take_over_as_secretary(self):
        """Somebody who isn't the circle's Secretary confirms taking over the
        meeting's secretary, dismissing changes nothing"""
        bob = User.objects.create_user("bob@example.com", full_name="Bob")
        Assignment.objects.create(
            role=self.kitchen.roles.get(core_role="secretary"), user=bob
        )
        Meeting.objects.filter(pk=self.meeting.pk).update(secretary=bob)
        page = self.page
        page.goto(f"{self.live_server_url}{self.meeting.get_absolute_url()}")
        page.evaluate("window.marker = 1")
        take_over = page.locator("form[action$='/secretary/'] button")

        page.once("dialog", lambda dialog: dialog.dismiss())
        take_over.click()
        page.wait_for_timeout(300)
        self.meeting.refresh_from_db()
        self.assertEqual(self.meeting.secretary, bob)

        page.once("dialog", lambda dialog: dialog.accept())
        take_over.click()
        page.wait_for_selector("form[action$='/secretary/']", state="detached")
        self.meeting.refresh_from_db()
        self.assertEqual(self.meeting.secretary, self.ada)
        self.assertSamePage()
        self.assertEqual(self.errors, [])
