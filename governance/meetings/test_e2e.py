"""End-to-end tests of meetings in a browser (htmx)

They run the real server (``LiveServerTestCase``, serving ``static/``
with the production bundle ``./runtests.sh`` builds) and Chromium through
Playwright, installed with ``uv run playwright install chromium``. Without
the browser or the bundle they're skipped; ``./runtests.sh --exclude-tag
e2e`` leaves them out, CI runs them.
"""

import os
import re

from django.conf import settings
from django.test import Client, LiveServerTestCase, tag
from django.urls import reverse
from django.utils import timezone

from governance.accounts.models import User
from governance.meetings.models import AgendaItem, Meeting
from governance.proposals.models import Proposal
from governance.roles.models import Assignment, ChecklistItem, Domain, Policy, Role


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
        page.locator("#agenda li.wb-row-link").first.click()  # Processing it
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

        # Ending the meeting, asked first (an item is open), shows its outputs
        page.locator("a[data-modal][href$='/end/']").click()
        page.wait_for_selector("#modal[open] >> text=End the meeting?")
        page.locator("#modal button[type=submit]").click()
        page.wait_for_selector("#meeting >> text=Outputs")
        # Celebrated, for a moment
        page.wait_for_selector(".wb-celebration .wb-confetti", state="attached")
        page.wait_for_selector(".wb-celebration", state="detached", timeout=5000)
        self.assertEqual(page.locator("#meeting >> text=Baker").count() > 0, True)

        # Links to other pages navigate as usual
        page.locator(
            f"#meeting a[href='{self.kitchen.get_absolute_url()}']"
        ).first.click()
        page.wait_for_url(f"**{self.kitchen.get_absolute_url()}")
        self.assertIsNone(page.evaluate("window.marker"))
        self.assertEqual(self.errors, [])

    def test_agenda_dragging_and_processing(self):
        """The secretary drags agenda items by their handles, clicking a row
        processes it"""
        for position, label in enumerate(["Tea", "Cake", "Soup"], 1):
            AgendaItem.objects.create(
                meeting=self.meeting, label=label, position=position
            )
        page = self.page
        page.goto(f"{self.live_server_url}{self.meeting.get_absolute_url()}")
        self.assertFalse(page.locator("#agenda .wb-no-js").first.is_visible())
        soup = page.locator("#agenda [data-agenda-item]", has_text="Soup")
        tea = page.locator("#agenda [data-agenda-item]", has_text="Tea")
        soup.locator("[data-agenda-handle]").drag_to(
            tea, target_position={"x": 20, "y": 5}
        )
        # The list changes right away in the browser, the server saves it
        # a moment later: wait for the database
        for _attempt in range(50):
            order = list(self.meeting.agenda_items.values_list("label", flat=True))
            if order[0] == "Soup":
                break
            page.wait_for_timeout(100)
        self.assertEqual(order, ["Soup", "Tea", "Cake"])

        # The reordered list swapped in, then clicking a row
        page.wait_for_load_state("networkidle")
        page.locator("#agenda [data-agenda-item]", has_text="Cake").click()
        page.wait_for_selector("#agenda .wb-current >> text=Cake")
        self.meeting.refresh_from_db()
        self.assertEqual(self.meeting.current_item.label, "Cake")
        self.assertEqual(self.errors, [])

    def test_outcome_autosaved(self):
        """The secretary's outcome saves itself a moment after typing, the
        item stays open"""
        Meeting.objects.filter(pk=self.meeting.pk).update(ended_at=timezone.now())
        meeting = Meeting.objects.create(
            circle=self.kitchen,
            kind=Meeting.TACTICAL,
            started_at=timezone.now(),
            secretary=self.ada,
            step="tensions",
        )
        item = AgendaItem.objects.create(meeting=meeting, label="Knives")
        meeting.current_item = item
        meeting.save()
        page = self.page
        page.goto(f"{self.live_server_url}{meeting.get_absolute_url()}")
        # Textareas grow with their text
        outcome = page.locator("textarea[name=outcome]")
        height = outcome.evaluate("textarea => textarea.offsetHeight")
        outcome.fill("Line\n" * 12)
        self.assertGreater(
            outcome.evaluate("textarea => textarea.offsetHeight"), height
        )
        page.fill("textarea[name=outcome]", "Bob buys new knives")
        for _attempt in range(30):
            item.refresh_from_db()
            if item.outcome:
                break
            page.wait_for_timeout(100)
        self.assertEqual(
            (item.outcome, item.is_completed), ("Bob buys new knives", False)
        )
        self.assertFalse(page.locator("#meeting-paused").is_visible())
        self.assertEqual(self.errors, [])

    def test_flow_scrolls_to_the_current_item(self):
        """Long results above: the column scrolls to the item being
        processed, also when another one is processed"""
        Meeting.objects.filter(pk=self.meeting.pk).update(ended_at=timezone.now())
        meeting = Meeting.objects.create(
            circle=self.kitchen,
            kind=Meeting.TACTICAL,
            started_at=timezone.now(),
            secretary=self.ada,
            step="tensions",
        )
        for position in range(1, 4):
            AgendaItem.objects.create(
                meeting=meeting,
                label=f"Done {position}",
                position=position,
                outcome="Long\n" * 40,
                is_completed=True,
            )
        first = AgendaItem.objects.create(meeting=meeting, label="First", position=4)
        AgendaItem.objects.create(meeting=meeting, label="Second", position=5)
        meeting.current_item = first
        meeting.save()
        page = self.page
        page.set_viewport_size({"width": 1280, "height": 800})
        page.goto(f"{self.live_server_url}{meeting.get_absolute_url()}")
        # The steps start right below the navigation, the heading is beside
        nav_bottom = page.evaluate(
            "document.querySelector('nav.navbar').getBoundingClientRect().bottom"
        )
        steps_top = page.evaluate(
            "document.querySelector('nav[aria-label=Steps]').getBoundingClientRect().top"
        )
        self.assertLess(steps_top - nav_bottom, 40)
        # A long agenda scrolls in its column too
        for position in range(10, 40):
            AgendaItem.objects.create(
                meeting=meeting, label=f"Later {position}", position=position
            )
        page.reload()
        # Only the column scrolls, not the page; it reaches the window's edge
        self.assertLessEqual(
            page.evaluate("document.documentElement.scrollHeight"), 800
        )
        self.assertAlmostEqual(
            page.evaluate(
                "document.querySelector('.wb-flow').getBoundingClientRect().bottom"
            ),
            800,
            delta=1,
        )
        visible = "(() => { const f = document.querySelector('.wb-flow').getBoundingClientRect(), c = document.querySelector('#current').getBoundingClientRect(); return c.top >= f.top - 1 && c.top < f.bottom })()"
        self.assertTrue(page.evaluate(visible))
        page.locator(".wb-flow").evaluate("flow => flow.scrollTo(0, 0)")
        self.assertFalse(page.evaluate(visible))
        page.locator("#agenda li", has_text="Second").click()
        page.wait_for_selector("#current >> text=Second")
        page.wait_for_function(visible)
        # The meeting's updates don't move the column
        scrolled = page.locator(".wb-flow").evaluate("flow => flow.scrollTop")
        AgendaItem.objects.create(meeting=meeting, label="Meanwhile", position=9)
        page.wait_for_selector("#agenda >> text=Meanwhile", timeout=8000)
        page.wait_for_timeout(300)
        self.assertAlmostEqual(
            page.locator(".wb-flow").evaluate("flow => flow.scrollTop"),
            scrolled,
            delta=2,
        )

        # A completed item's row leads to its result, "Reopen" goes back
        page.locator("#agenda li", has_text="Done 1").click()
        page.wait_for_function(
            "document.querySelector('#results section').getBoundingClientRect().top"
            " >= document.querySelector('.wb-flow').getBoundingClientRect().top - 1"
        )
        page.locator("#results section", has_text="Done 1").locator(
            "button", has_text="Reopen"
        ).click()
        page.wait_for_selector("#current >> text=Done 1")
        self.assertEqual(self.errors, [])

    def test_amending_scrolls_to_the_form(self):
        """The form opened below a long list of roles comes into view"""
        for number in range(30):
            Role.objects.create(name=f"Role {number:02}", circle=self.kitchen)
        proposal = Proposal.objects.create(
            circle=self.kitchen,
            proposer=self.ada,
            role=self.cook,
            tension="Roles",
            status=Proposal.IN_MEETING,
            meeting=self.meeting,
            created_at=timezone.now(),
        )
        AgendaItem.objects.create(
            meeting=self.meeting, proposal=proposal, label="Roles"
        )
        page = self.page
        page.set_viewport_size({"width": 1280, "height": 800})
        page.goto(f"{self.live_server_url}{self.meeting.get_absolute_url()}")
        page.locator("#agenda li.wb-row-link").first.click()  # Processing it
        page.wait_for_selector(".wb-amend-area")
        page.locator(".wb-amend-area summary", has_text="role").click()
        page.locator(".wb-amend-area li", has_text="Role 05").locator(
            "a.btn", has_text="Change"
        ).click()
        page.wait_for_selector("#amend form")
        page.wait_for_function(
            "(() => { const top = document.querySelector('#amend').getBoundingClientRect().top;"
            " return top >= 0 && top < window.innerHeight / 2 })()",
            timeout=2000,
        )
        # Paused while editing, which the secretary knows: no notice
        page.evaluate("document.activeElement?.blur()")
        page.evaluate("meetingIsIdle()")
        self.assertFalse(page.evaluate("meetingIsIdle()"))
        self.assertFalse(page.locator("#meeting-paused").is_visible())
        self.assertEqual(self.errors, [])

    def test_paused_notice(self):
        """Updates paused for longer than a moment (typing, something open):
        a notice says so until it continues"""
        page = self.page
        page.goto(f"{self.live_server_url}{self.meeting.get_absolute_url()}")
        notice = page.locator("#meeting-paused")
        page.focus("input[name=label]")
        self.assertFalse(page.evaluate("meetingIsIdle()"))
        self.assertFalse(notice.is_visible())  # Typing a moment
        page.evaluate("meetingIsIdle()")
        self.assertTrue(notice.is_visible())
        page.locator("h1").click()
        self.assertTrue(page.evaluate("meetingIsIdle()"))
        self.assertFalse(notice.is_visible())
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
        page.locator("#agenda li.wb-row-link").first.click()  # Processing it
        page.wait_for_selector(".wb-amend-area")

        # Moving the policy out of the bakery
        page.locator(".wb-amend-area a[href*='/move/']").click()
        page.locator("#amend li", has_text="Noise").locator("button").click()
        page.wait_for_selector("#amend form", state="detached")
        self.assertIn(
            "from Bakery",
            page.locator("#meeting ul.list-unstyled:not(.wb-summary)").inner_text(),
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

        # Deleting asks first
        page.locator("a[data-modal][href$='/delete/']").click()
        page.wait_for_selector("#modal[open] >> text=Delete this checklist item?")
        page.locator("#modal button[type=submit]").click()
        page.wait_for_selector("main >> text=Sharpen the knives", state="detached")
        self.assertFalse(ChecklistItem.objects.exists())

        # In a meeting its updates continue behind the modal ("Take over",
        # somebody else is the secretary)
        bob = User.objects.create_user("bob@example.com", full_name="Bob")
        Meeting.objects.filter(pk=self.meeting.pk).update(secretary=bob)
        page.goto(f"{self.live_server_url}{self.meeting.get_absolute_url()}")
        page.locator("a[data-modal][href$='/secretary/']").click()
        page.wait_for_selector("#modal[open]")
        AgendaItem.objects.create(meeting=self.meeting, label="Meanwhile", position=9)
        page.wait_for_selector("#agenda >> text=Meanwhile", timeout=8000)
        self.assertEqual(page.locator("#modal[open]").count(), 1)
        self.assertEqual(self.errors, [])

    def test_domain_policies(self):
        """A domain's link opens its policies and scrolls there"""
        domain = Domain.objects.create(role=self.cook, text="The stove")
        for title in ["Gas", "Cleaning"]:
            Policy.objects.create(role=self.cook, domain=domain, title=title)
        page = self.page
        page.goto(f"{self.live_server_url}{self.cook.get_absolute_url()}")
        self.assertEqual(page.locator("details[open]").count(), 0)
        page.locator("a[data-open-details]", has_text="2 policies").click()
        page.wait_for_function(
            "document.querySelectorAll('details[id^=policy-][open]').length === 2"
        )
        self.assertEqual(self.errors, [])

    def test_history_day(self):
        """A day of the history linked from the role's page shows what
        changed, unfolded"""
        import datetime as dt

        from governance.history.models import Change

        Change.objects.create(
            date=dt.date(2026, 1, 2),
            role=self.cook,
            kind="purpose",
            old="Frying",
            new="Food",
        )
        page = self.page
        page.goto(f"{self.live_server_url}{self.cook.get_absolute_url()}")
        page.locator('main a[href*="day=2026-01-02"]').click()
        page.wait_for_url(
            re.compile(r"/history/\?role=\d+&day=2026-01-02#day-2026-01-02$")
        )
        self.assertTrue(
            page.locator("#day-2026-01-02 details").get_attribute("open") is not None
        )
        self.assertEqual(self.errors, [])

    def test_response_text(self):
        """The response's text only for the responses taking one, and never
        hidden while it has text"""
        import datetime as dt

        bob = User.objects.create_user("bob@example.com", full_name="Bob")
        Assignment.objects.create(role=self.cook, user=bob)
        now = timezone.now()
        proposal = Proposal.objects.create(
            circle=self.kitchen,
            role=self.cook,
            proposer=bob,
            tension="Bread",
            status=Proposal.PUBLISHED,
            created_at=now,
            published_at=now,
            deadline=now + dt.timedelta(days=2),
            instructions=[
                {"op": "add", "path": "/roles/n1"},
                {"op": "add", "path": "/roles/n1/name", "value": "Baker"},
            ],
        )
        page = self.page
        page.goto(f"{self.live_server_url}{proposal.get_absolute_url()}")
        text = page.locator("textarea[name=text]")
        self.assertFalse(text.is_visible())
        page.get_by_label("question or comment").check()
        self.assertTrue(text.is_visible())
        text.fill("Why?")
        page.get_by_label("no objection").check()
        self.assertTrue(text.is_visible())  # Not dropped unseen
        text.fill("")
        page.get_by_label("discuss in a meeting").check()
        self.assertTrue(text.is_visible())
        page.get_by_label("no objection").check()
        self.assertFalse(text.is_visible())
        self.assertEqual(self.errors, [])

    def test_role_leads(self):
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

    def test_asked_before_starting(self):
        """In a role Enter cancels, in a circle (not the Secretary) it starts"""
        page = self.page
        page.goto(f"{self.live_server_url}{self.cook.get_absolute_url()}")
        # A role's meetings are in the menu
        page.locator("main details.wb-menu summary").click()
        page.locator("a[data-modal]", has_text="Start a governance meeting").click()
        page.wait_for_selector("#modal[open] [data-modal-close]:focus")
        page.keyboard.press("Enter")
        page.wait_for_selector("#modal[open]", state="detached")
        self.assertFalse(Meeting.objects.filter(circle=self.cook).exists())

        bakery = Role.objects.create(name="Bakery", is_circle=True, circle=self.kitchen)
        bakery.create_core_roles()
        bob = User.objects.create_user("bob@example.com", full_name="Bob")
        Assignment.objects.create(
            role=bakery.roles.get(core_role="secretary"), user=bob
        )
        Assignment.objects.create(
            role=Role.objects.create(name="Baker", circle=bakery), user=self.ada
        )
        page.goto(f"{self.live_server_url}{bakery.get_absolute_url()}")
        # The circle's Meetings card (the menu has it too)
        page.locator(
            "section a[data-modal]", has_text="Start a tactical meeting"
        ).click()
        page.wait_for_selector("#modal[open] button[type=submit]:focus")
        page.keyboard.press("Enter")
        page.wait_for_url("**/meetings/*/")
        self.assertEqual(Meeting.objects.get(circle=bakery).kind, Meeting.TACTICAL)
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

        # Hovering a role shows its Role Leads next to the mouse, the labels
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

    def test_phone(self):
        """On phones the heading comes first, then the steps and the item
        being processed, the agenda below; its rows stay rows"""
        item = AgendaItem.objects.create(meeting=self.meeting, label="Knives")
        long = AgendaItem.objects.create(
            meeting=self.meeting, label="Who sharpens the tools " * 4, position=2
        )
        self.meeting.current_item = long
        self.meeting.step = "agenda"
        self.meeting.save()
        page = self.page
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(f"{self.live_server_url}{self.meeting.get_absolute_url()}")
        # Buttons with an icon don't wrap beside a long text
        done = page.locator("#current button", has_text="Done").bounding_box()
        self.assertLess(done["height"], 35)

        self.meeting.current_item = item
        self.meeting.step = "agenda"
        self.meeting.save()
        page = self.page
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(f"{self.live_server_url}{self.meeting.get_absolute_url()}")

        def top(selector):
            return page.locator(selector).first.bounding_box()["y"]

        self.assertLess(top("h1"), top("nav[aria-label=Steps]"))
        self.assertLess(top("nav[aria-label=Steps]"), top("#current"))
        self.assertLess(top("#current"), top("#agenda"))
        row = page.locator("#agenda li", has_text="Knives")
        handle = row.locator("[data-agenda-handle]").bounding_box()
        remove = row.locator("form[action$='/remove/'] button").bounding_box()
        self.assertLess(row.bounding_box()["height"], 50)
        self.assertLess(abs(handle["y"] - remove["y"]), 10)
        self.assertGreater(remove["x"], 300)
        self.assertEqual(page.evaluate("document.documentElement.scrollWidth"), 390)
        self.assertEqual(self.errors, [])

    def test_menu(self):
        """What isn't needed often is in a menu, closed by clicking
        elsewhere and with Escape"""
        page = self.page
        page.goto(f"{self.live_server_url}{self.kitchen.get_absolute_url()}")
        link = page.locator("main details.wb-menu a", has_text="All meetings")
        self.assertFalse(link.is_visible())
        summary = page.locator("main details.wb-menu summary")
        summary.click()
        self.assertTrue(link.is_visible())
        page.locator("h1").click()
        self.assertFalse(link.is_visible())
        summary.click()
        page.keyboard.press("Escape")
        self.assertFalse(link.is_visible())
        summary.click()
        link.click()
        page.wait_for_url(f"**/roles/{self.kitchen.pk}/meetings/")
        self.assertEqual(self.errors, [])

    def test_mail_addresses(self):
        """The user's menu leads to the mail addresses, a button copies a
        group's"""
        self.context.grant_permissions(
            ["clipboard-read", "clipboard-write"], origin=self.live_server_url
        )
        page = self.page
        page.goto(f"{self.live_server_url}/")
        page.locator("nav details.wb-menu summary").click()
        page.locator("nav a", has_text="Mail addresses").click()
        page.wait_for_url("**/people/addresses/")
        page.locator(f"#circle-{self.kitchen.pk} [data-copy]").click()
        self.assertEqual(
            page.evaluate("navigator.clipboard.readText()"), "Ada <ada@example.com>"
        )
        self.assertEqual(self.errors, [])

    def test_filters(self):
        """Changing a filter loads the list, the button is for browsers
        without JavaScript"""
        page = self.page
        page.goto(f"{self.live_server_url}/history/")
        self.assertFalse(page.locator("[data-filter-submit]").is_visible())
        page.locator("label", has_text="With assignments").click()
        page.wait_for_url("**/history/?assignments=on")
        page.select_option("select[name=role]", str(self.kitchen.pk))
        page.wait_for_url(f"**/history/?assignments=on&role={self.kitchen.pk}")
        page.locator("a", has_text="Reset").click()
        page.wait_for_url("**/history/?")
        self.assertEqual(self.errors, [])

    def test_call_tactical_meeting(self):
        """Calling an ad hoc meeting: roles filtered as you type, then who
        is invited"""
        Role.objects.create(name="Waiter", circle=self.kitchen)
        page = self.page
        page.goto(f"{self.live_server_url}/meetings/tactical/new/")
        page.fill("[data-filter-rows]", "coo")
        self.assertTrue(page.locator("label", has_text="Cook").is_visible())
        self.assertFalse(page.locator("label", has_text="Waiter").is_visible())
        page.locator("label", has_text="Cook").click()
        page.fill("[data-filter-rows]", "")
        page.locator("button", has_text="Next").click()
        page.wait_for_selector("input[name=attendee]:checked")
        page.locator("button", has_text="Start the meeting").click()
        page.wait_for_url("**/meetings/*/")
        meeting = Meeting.objects.get(circle=None)
        self.assertEqual(list(meeting.invited_roles.all()), [self.cook])
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
        take_over = page.locator("a[data-modal][href$='/secretary/']")

        # Asked in a modal, cancelling changes nothing
        take_over.click()
        page.wait_for_selector("#modal[open] >> text=You aren't the circle's Secretary")
        page.locator("#modal [data-modal-close]").click()
        page.wait_for_selector("#modal[open]", state="detached")
        self.meeting.refresh_from_db()
        self.assertEqual(self.meeting.secretary, bob)

        take_over.click()
        page.locator("#modal[open] button[type=submit]").click()
        page.wait_for_selector("a[href$='/secretary/']", state="detached")
        self.meeting.refresh_from_db()
        self.assertEqual(self.meeting.secretary, self.ada)
        self.assertEqual(self.errors, [])
