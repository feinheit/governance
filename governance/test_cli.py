import datetime as dt
import json
import tempfile
import urllib.parse
from pathlib import Path
from unittest.mock import patch

import gov
from click.shell_completion import ShellComplete, get_completion_class
from click.testing import CliRunner
from django.http import HttpResponsePermanentRedirect
from django.test import Client, TestCase
from django.utils import timezone
from django.utils.translation import deactivate_all

from governance import cli_version
from governance.accounts.models import APIToken, User
from governance.meetings.models import AgendaItem, Meeting
from governance.proposals.models import Proposal
from governance.roles.models import (
    Accountability,
    Assignment,
    Domain,
    Link,
    Note,
    Policy,
    Role,
)


class Response:
    """The parts of a requests response the CLI uses"""

    def __init__(self, response):
        self.status_code = response.status_code
        self.ok = response.status_code < 400
        self.headers = response.headers
        self.text = response.content.decode()
        self._response = response

    def json(self):
        return self._response.json()


class CLITest(TestCase):
    """Runs the real CLI against the API, requests go through the test client"""

    def setUp(self):
        self.api_client = Client()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        for patcher in [
            patch.object(gov.core.requests, "request", self.request),
            patch.object(gov.core, "CONFIG", self.directory / "governance.toml"),
            patch.object(gov.core, "BUG_REPORTS", self.directory / "reports"),
            patch.object(gov.core, "CACHE", self.directory / "cache"),
            patch.object(gov.core.console, "_width", 200),
        ]:
            patcher.start()
            self.addCleanup(patcher.stop)
        gov.core._check_version.cache_clear()

        self.ada = User.objects.create_user("ada@example.com", full_name="Ada")
        self.kitchen = Role.objects.create(
            name="Kitchen",
            is_circle=True,
            purpose="Food for everyone",
            async_acceptance_days=4,
        )
        self.kitchen.create_core_roles()
        self.cook = Role.objects.create(name="Cook", circle=self.kitchen)
        Accountability.objects.create(role=self.cook, text="Cooking soup")
        Assignment.objects.create(role=self.cook, user=self.ada, focus="Soup")

    def tearDown(self):
        deactivate_all()

    def request(
        self, method, url, *, headers, timeout, params=None, json=None, **kwargs
    ):
        path = urllib.parse.urlsplit(url).path
        if method == "GET":
            response = self.api_client.get(path, params, headers=headers)
        else:
            response = getattr(self.api_client, method.lower())(
                path, json, content_type="application/json", headers=headers
            )
        return Response(response)

    def gov(self, *args, access="write", input=None, token=None):
        if not token:
            _token, token = APIToken.create_for(
                user=self.ada, title="Tests", access=access
            )
        config = gov.core.read_config()
        config["installations"]["http://testserver"] = {"token": token}
        gov.core.write_config(config)
        # rich chooses colors and links when creating the console, from
        # the real stdout: plain text as into a pipe, also in a terminal
        with patch.object(gov.core.console, "_color_system", None):
            result = CliRunner().invoke(
                gov.cli,
                [str(arg) for arg in args],
                env={"GOVERNANCE_URL": "http://testserver", "GOV_DEBUG": "1"},
                input=input,
            )
        if result.exception and not isinstance(result.exception, SystemExit):
            raise result.exception
        return result

    def test_reading(self):
        """Who you are, circles, roles and the search"""
        result = self.gov("me")
        self.assertIn("Ada", result.output)
        self.assertIn(f"{self.cook.pk}", result.output)
        self.assertIn("Soup", result.output)

        result = self.gov("circles")
        self.assertIn("Kitchen", result.output)
        self.assertIn("Food for everyone", result.output)

        result = self.gov("roles", "show", self.cook.pk)
        self.assertIn("Cooking soup", result.output)
        self.assertIn("Ada", result.output)
        result = self.gov("circles", "show", self.kitchen.pk)
        self.assertIn("Cook", result.output)
        self.assertIn("Facilitator", result.output)
        # Core roles with their constitutional texts
        secretary = self.kitchen.roles.get(core_role="secretary")
        result = self.gov("roles", "show", secretary.pk)
        self.assertIn("Stabilize the Circle", result.output)
        self.assertIn("Scheduling Governance Meetings", result.output)
        self.assertIn("All governance records", result.output)

        self.assertIn("Cooking soup", self.gov("search", "SOUP").output)
        # People with their circles
        result = self.gov("search", "ada")
        self.assertIn("People", result.output)
        self.assertIn("Kitchen", result.output)
        result = self.gov("search", "ada", "--json")
        self.assertIn('"people"', result.output)
        self.assertIn("Nothing found.", self.gov("search", "nothing").output)
        # Links by their keywords
        Link.objects.create(
            role=self.cook,
            title="Recipes",
            url="https://example.com/recipes/",
            description="Soup, stew",
        )
        result = self.gov("search", "stew")
        self.assertIn("Links", result.output)
        self.assertIn("Recipes", result.output)
        self.assertIn("Cook", result.output)
        result = self.gov("search", "stew", "--json")
        self.assertIn('"https://example.com/recipes/"', result.output)
        # Notes by their texts, opened on the role's page
        note = Note.objects.create(role=self.cook, title="Pots", body="Big for goulash")
        result = self.gov("search", "goulash")
        self.assertIn("Notes", result.output)
        self.assertIn("Pots", result.output)
        result = self.gov("search", "goulash", "--json")
        self.assertIn(f"/roles/{self.cook.pk}/#note-{note.pk}", result.output)
        # Archived roles only on request, marked
        Role.objects.create(
            name="Old soup cook", circle=self.kitchen, archived_on=dt.date(2026, 1, 1)
        )
        self.assertNotIn("Old soup cook", self.gov("search", "old", "soup").output)
        result = self.gov("search", "old", "soup", "--archived")
        self.assertIn("Old soup cook (archived on 2026-01-01)", result.output)

    def test_proposals(self):
        """Drafts with instructions, their problems, publishing"""
        instructions = self.directory / "instructions.yaml"
        instructions.write_text(
            "- op: add\n"
            "  path: /roles/n1\n"
            "- op: add\n"
            "  path: /roles/n1/name\n"
            "  value: Baker\n"
        )
        result = self.gov(
            "proposals",
            "create",
            "--circle",
            self.kitchen.pk,
            "--role",
            self.cook.pk,
            "--tension",
            "-",
            "--instructions",
            instructions,
            input="No bread\n",
        )
        proposal = Proposal.objects.get()
        self.assertEqual(proposal.tension, "No bread")
        self.assertIn("No bread", result.output)

        result = self.gov("proposals", "show", proposal.pk)
        self.assertIn("Tension", result.output)
        self.assertIn("draft", result.output)

        result = self.gov("proposals", "update", proposal.pk, "--tension", "No bread!")
        proposal.refresh_from_db()
        self.assertEqual(proposal.tension, "No bread!")
        result = self.gov("proposals", "update", proposal.pk)
        self.assertIn("Nothing to change", result.output)

        # Read only access is enough for looking, not for changes
        result = self.gov("proposals", "publish", proposal.pk, access="read")
        self.assertEqual(result.exit_code, 1)
        self.assertIn("only allows reading", result.output)

        self.assertIn("No bread!", self.gov("proposals").output)
        self.assertIn(
            "No proposals.", self.gov("proposals", "--status", "adopted").output
        )

    def test_plain_mentions(self):
        """ "@Name" without the autocomplete becomes a mention, in the tension
        and in the texts of the changes, not in names"""
        instructions = self.directory / "instructions.yaml"
        instructions.write_text(
            "- op: add\n"
            "  path: /roles/n1\n"
            "- op: add\n"
            "  path: /roles/n1/name\n"
            "  value: '@Cook'\n"
            "- op: add\n"
            "  path: /roles/n1/accountabilities/n2/description\n"
            "  value: Bread for @cook\n"
        )
        self.gov(
            "proposals",
            "create",
            "--circle",
            self.kitchen.pk,
            "--role",
            self.cook.pk,
            "--tension",
            "Ask @Cook, not @Baker",
            "--instructions",
            instructions,
        )
        proposal = Proposal.objects.get()
        mention = f"@[Cook](role:{self.cook.pk})"
        self.assertEqual(proposal.tension, f"Ask {mention}, not @Baker")
        self.assertEqual(
            [i.get("value") for i in proposal.instructions],
            [None, "@Cook", f"Bread for {mention}"],
        )

    def test_publish(self):
        proposal = Proposal.objects.create(
            circle=self.kitchen,
            role=self.cook,
            proposer=self.ada,
            tension="Soup",
            instructions=[
                {"op": "add", "path": "/roles/n1"},
                {"op": "add", "path": "/roles/n1/name", "value": "Baker"},
            ],
            created_at="2026-11-05T10:00:00Z",
        )
        result = self.gov("proposals", "publish", proposal.pk)
        self.assertEqual(result.exit_code, 0, result.output)
        proposal.refresh_from_db()
        # Ada is the circle's only member, publishing adopts it right away
        self.assertIn(proposal.status, {Proposal.PUBLISHED, Proposal.ADOPTED})
        self.assertIn(proposal.get_absolute_url(), result.output)

    def test_days_like_the_pages(self):
        """The day of adoption like the pages, not the deadline's day in UTC"""
        import datetime as dt

        bob = User.objects.create_user("bob@example.com", full_name="Bob")
        Assignment.objects.create(role=self.cook, user=bob)
        deadline = dt.datetime(2026, 11, 11, 23, 30, tzinfo=dt.UTC)  # Zurich: 12th
        proposal = Proposal.objects.create(
            circle=self.kitchen,
            role=self.cook,
            proposer=bob,
            tension="Soup",
            status=Proposal.PUBLISHED,
            created_at=deadline - dt.timedelta(days=5),
            published_at=deadline - dt.timedelta(days=5),
            deadline=deadline,
            instructions=[
                {"op": "add", "path": "/roles/n1"},
                {"op": "add", "path": "/roles/n1/name", "value": "Baker"},
            ],
        )
        self.assertEqual(proposal.adopted_on, dt.date(2026, 11, 12))
        for args in [("proposals", "show", proposal.pk), ("proposals", "open")]:
            with self.subTest(args=args):
                output = self.gov(*args).output
                self.assertIn("2026-11-12", output)
                self.assertNotIn("2026-11-11", output)

    def test_responding(self):
        """Open proposals of one's circles, responding to them"""
        import datetime as dt

        from django.utils import timezone

        bob = User.objects.create_user("bob@example.com", full_name="Bob")
        eve = User.objects.create_user("eve@example.com", full_name="Eve")
        dishes = Role.objects.create(name="Dishes", circle=self.kitchen)
        Assignment.objects.create(role=dishes, user=bob)
        Assignment.objects.create(role=dishes, user=eve)
        now = timezone.now()
        published = {
            "circle": self.kitchen,
            "role": dishes,
            "proposer": bob,
            "status": Proposal.PUBLISHED,
            "created_at": now,
            "published_at": now,
            "instructions": [
                {
                    "op": "replace",
                    "path": f"/roles/{dishes.pk}/name",
                    "original_value": "Dishes",
                    "value": "Washing up",
                }
            ],
        }
        later = Proposal.objects.create(
            **published
            | {
                # Not conflicting with the sooner one, adopted first
                "instructions": [
                    {
                        "op": "replace",
                        "path": f"/roles/{dishes.pk}/aim",
                        "original_value": "",
                        "value": "Clean plates",
                    }
                ]
            },
            tension="Later",
            deadline=now + dt.timedelta(days=5),
        )
        sooner = Proposal.objects.create(
            **published, tension="Sooner", deadline=now + dt.timedelta(days=2)
        )
        # Not in Ada's circles
        garden = Role.objects.create(name="Garden", is_circle=True)
        Proposal.objects.create(
            **published | {"circle": garden},
            tension="Flowers",
            deadline=now + dt.timedelta(days=1),
        )

        result = self.gov("proposals", "open")
        self.assertNotIn("Flowers", result.output)
        self.assertLess(result.output.index("Sooner"), result.output.index("Later"))

        result = self.gov("proposals", "consent", sooner.pk)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Responded", result.output)
        result = self.gov("proposals", "open")
        self.assertIn("no objection", result.output)
        result = self.gov("proposals", "comment", sooner.pk, "Why now?")
        self.assertEqual(sooner.responses.get(kind="comment").text, "Why now?")
        # Eve consents too: everybody did, it's adopted
        eve_client = Client()
        eve_client.force_login(eve)
        eve_client.post(
            f"/proposals/{sooner.pk}/respond/", {"kind": "consent", "text": ""}
        )
        sooner.refresh_from_db()
        self.assertEqual(sooner.status, Proposal.ADOPTED)

        result = self.gov(
            "proposals", "request-meeting", later.pk, "--concern", "-", input="Hm\n"
        )
        self.assertIn("next governance meeting", result.output)
        later.refresh_from_db()
        self.assertEqual(later.status, Proposal.IN_MEETING)
        self.assertEqual(later.responses.get().text, "Hm")
        # Not open for consents anymore, the server explains
        result = self.gov("proposals", "consent", later.pk)
        self.assertEqual(result.exit_code, 1)
        self.assertIn("Select a valid choice", result.output)
        # A question needs its text
        result = self.gov("proposals", "comment", later.pk, " ")
        self.assertIn("Please explain", result.output)

    def test_async_round_trip(self):
        """Drafted and published with gov, answered in the browser, adopted
        at the deadline by the daily task, read back with gov"""
        import datetime as dt

        import time_machine
        from django.core import mail
        from django.core.management import call_command

        bob = User.objects.create_user("bob@example.com", full_name="Bob")
        eve = User.objects.create_user("eve@example.com", full_name="Eve")
        Assignment.objects.create(
            role=self.kitchen.roles.get(core_role="secretary"), user=bob
        )
        Assignment.objects.create(
            role=Role.objects.create(name="Waiter", circle=self.kitchen), user=eve
        )
        soup = Accountability.objects.get(role=self.cook)
        instructions = self.directory / "instructions.yaml"
        instructions.write_text(
            "- op: replace\n"
            f"  path: /roles/{self.cook.pk}/accountabilities/{soup.pk}/description\n"
            "  original_value: Cooking soup\n"
            "  value: Cooking soup and stew\n"
        )
        result = self.gov(
            "proposals",
            "create",
            "--circle",
            self.kitchen.pk,
            "--role",
            self.cook.pk,
            "--tension",
            "Stew too",
            "--instructions",
            instructions,
        )
        self.assertEqual(result.exit_code, 0, result.output)
        proposal = Proposal.objects.get()
        with self.captureOnCommitCallbacks(execute=True):
            result = self.gov("proposals", "publish", proposal.pk)
        self.assertEqual(result.exit_code, 0, result.output)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.PUBLISHED)
        self.assertEqual(
            sorted(m.to[0] for m in mail.outbox),
            ["ada@example.com", "bob@example.com", "eve@example.com"],
        )

        # Bob consents, Eve only asks: no decision before the deadline
        self.client.force_login(bob)
        self.client.post(f"/proposals/{proposal.pk}/respond/", {"kind": "consent"})
        self.client.force_login(eve)
        self.client.post(
            f"/proposals/{proposal.pk}/respond/",
            {"kind": "comment", "text": "Which stew?"},
        )
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.PUBLISHED)
        # The proposer sees the question to answer, the consents counted
        output = self.gov("proposals", "show", proposal.pk).output
        self.assertIn("Which stew?", output)
        self.assertIn("Eve", output)
        self.assertIn("1 of 2", output)
        self.assertNotIn("Bob", output)
        data = json.loads(self.gov("proposals", "show", proposal.pk, "--json").output)
        self.assertEqual(
            {key: data["responses"][key] for key in ["consents", "others"]},
            {"consents": 1, "others": 2},
        )
        self.assertEqual(
            [(r["user"], r["kind"], r["text"]) for r in data["responses"]["entries"]],
            [("Eve", "comment", "Which stew?")],
        )

        mail.outbox = []
        with (
            time_machine.travel(proposal.deadline + dt.timedelta(minutes=1)),
            self.captureOnCommitCallbacks(execute=True),
        ):
            call_command("hourly_tasks")
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.ADOPTED)
        self.assertIn("eve@example.com", [m.to[0] for m in mail.outbox])

        self.assertIn("adopted", self.gov("proposals", "show", proposal.pk).output)
        self.assertIn(
            "Cooking soup and stew", self.gov("roles", "show", self.cook.pk).output
        )
        self.assertIn("Stew too", self.gov("proposals", "--status", "adopted").output)

    def test_versions(self):
        """Older CLIs are told to upgrade, too old ones are rejected"""
        with patch.object(gov.core, "VERSION", "0.0.1"):
            result = self.gov("me")
        self.assertIn("too old", result.output)
        self.assertEqual(result.exit_code, 1)
        current = cli_version.LATEST
        with (
            patch.object(cli_version, "LATEST", "99.0.0"),
            patch.object(gov.core, "VERSION", current),
        ):
            result = self.gov("me")
        self.assertIn("gov 99.0.0 is available", result.output)

    def test_notes(self):
        """Adding (the text from stdin), changing, listing and removing a
        circle's notes"""
        result = self.gov(
            "notes", "add", self.kitchen.pk, "Pots", "--file", "-", input="- *Big*\n"
        )
        note = json.loads(self.gov("notes", "list", self.kitchen.pk, "--json").output)[
            0
        ]
        self.assertEqual(result.output, f"Added note {note['id']} Pots.\n")
        self.assertEqual(note["body"], "- *Big*")
        result = self.gov("notes", "update", note["id"], "--body", "Small ones too")
        self.assertEqual(result.output, f"Changed note {note['id']} Pots.\n")
        result = self.gov("notes", "list", self.kitchen.pk)
        self.assertIn("Small ones too", result.output)
        self.assertNotIn("[bold]", result.output)
        self.assertIn("Pots", self.gov("circles", "show", self.kitchen.pk).output)
        result = self.gov("notes", "update", note["id"])
        self.assertIn("Nothing to change", result.output)
        result = self.gov("notes", "update", note["id"], "--title", "")
        self.assertEqual(result.exit_code, 1)
        self.assertIn("400", result.output)
        self.assertIn("Removed Pots", self.gov("notes", "remove", note["id"]).output)
        self.assertIn("No notes.", self.gov("notes", "list", self.kitchen.pk).output)

    def test_tensions(self):
        """Adding (the description from stdin), changing, listing and removing
        tensions of a circle's inbox; only its members use it"""
        result = self.gov(
            "tensions",
            "add",
            self.kitchen.pk,
            "Knives",
            "--file",
            "-",
            input="*Dull*\n",
        )
        tension = json.loads(
            self.gov("tensions", "list", self.kitchen.pk, "--json").output
        )[0]
        self.assertEqual(result.output, f"Added tension {tension['id']} Knives.\n")
        self.assertEqual(tension["description"], "*Dull*")
        self.assertEqual(tension["owner"]["email"], "ada@example.com")
        result = self.gov("tensions", "update", tension["id"], "--title", "Knives dull")
        self.assertEqual(
            result.output, f"Changed tension {tension['id']} Knives dull.\n"
        )
        result = self.gov("tensions", "list", self.kitchen.pk)
        self.assertIn("Knives dull – Ada", result.output)
        result = self.gov("tensions", "update", tension["id"])
        self.assertIn("Nothing to change", result.output)
        self.gov("tensions", "update", tension["id"], "--private")
        self.assertIn(
            "Knives dull – Ada", self.gov("tensions", "list", self.kitchen.pk).output
        )
        self.assertIn("private", self.gov("tensions", "list", self.kitchen.pk).output)
        # Into another inbox of hers, not into others'
        bar = Role.objects.create(name="Bar", is_circle=True, circle=self.kitchen)
        sales = Role.objects.create(name="Sales", is_circle=True)
        result = self.gov("tensions", "update", tension["id"], "--circle", bar.pk)
        self.assertIn("403", result.output)
        Assignment.objects.create(
            role=Role.objects.create(name="Barista", circle=bar), user=self.ada
        )
        self.gov("tensions", "update", tension["id"], "--circle", bar.pk)
        self.assertIn("Knives dull", self.gov("tensions", "list", bar.pk).output)
        result = self.gov("tensions", "update", tension["id"], "--circle", sales.pk)
        self.assertIn("403", result.output)
        self.gov("tensions", "update", tension["id"], "--circle", self.kitchen.pk)
        self.assertIn(
            "Removed Knives dull", self.gov("tensions", "remove", tension["id"]).output
        )
        self.assertIn(
            "The inbox is empty.", self.gov("tensions", "list", self.kitchen.pk).output
        )
        result = self.gov("tensions", "add", sales.pk, "Prices")
        self.assertEqual(result.exit_code, 1)
        self.assertIn("403", result.output)

    def test_links(self):
        """Adding, changing, listing and removing a circle's links"""
        result = self.gov(
            "links", "add", self.kitchen.pk, "Projects", "https://example.com/p"
        )
        self.assertIn("Projects", result.output)
        link = json.loads(self.gov("links", "list", self.kitchen.pk, "--json").output)[
            0
        ]
        self.gov("links", "update", link["id"], "--description", "To-dos")
        result = self.gov("links", "list", self.kitchen.pk)
        self.assertIn("To-dos", result.output)
        self.assertIn("https://example.com/p", result.output)
        self.assertIn("Projects", self.gov("circles", "show", self.kitchen.pk).output)
        result = self.gov("links", "update", link["id"], "--url", "nope")
        self.assertEqual(result.exit_code, 1)
        self.assertIn("400", result.output)
        self.assertIn(
            "Removed Projects", self.gov("links", "remove", link["id"]).output
        )
        self.assertIn("No links.", self.gov("links", "list", self.kitchen.pk).output)

    def test_checklist_and_metrics(self):
        """Adding, moving, listing and removing checklist items and metrics;
        metrics need the Circle Leads"""
        result = self.gov(
            "checklist", "add", self.cook.pk, "Fridge cleaned", "--frequency", "weekly"
        )
        self.assertIn("Fridge cleaned", result.output)
        item = json.loads(self.gov("checklist", "list", self.cook.pk, "--json").output)[
            0
        ]
        self.assertEqual(
            (item["whole_circle"], item["reported_in_id"]), (False, self.kitchen.pk)
        )
        # Not reported by the anchor circle in a circle above
        result = self.gov("checklist", "update", item["id"], "--role", self.kitchen.pk)
        self.assertEqual(result.exit_code, 1)
        self.assertIn("400", result.output)
        self.gov(
            "checklist",
            "update",
            item["id"],
            "--role",
            self.kitchen.pk,
            "--whole-circle",
        )
        result = self.gov("checklist", "list", self.kitchen.pk)
        self.assertIn("Kitchen (whole circle)", result.output)
        self.assertIn(
            "No checklist items.", self.gov("checklist", "list", self.cook.pk).output
        )
        # Back to a role, which isn't the whole circle's
        result = self.gov("checklist", "update", item["id"], "--role", self.cook.pk)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn(
            "Fridge cleaned", self.gov("checklist", "list", self.cook.pk).output
        )
        result = self.gov("checklist", "update", item["id"])
        self.assertIn("Nothing to change", result.output)
        self.assertIn(
            "Removed Fridge cleaned", self.gov("checklist", "remove", item["id"]).output
        )

        result = self.gov("metrics", "add", self.cook.pk, "Soups sold")
        self.assertEqual(result.exit_code, 1)
        self.assertIn("403", result.output)
        Assignment.objects.create(
            role=self.kitchen.roles.get(core_role="lead"), user=self.ada
        )
        self.gov("metrics", "add", self.cook.pk, "Soups sold")
        self.assertIn("Soups sold", self.gov("metrics", "list", self.cook.pk).output)
        result = self.gov("search", "soups")
        self.assertIn("Metrics", result.output)
        self.assertIn("Soups sold", result.output)

    def test_policies(self):
        from governance.roles.models import Domain, Policy

        Policy.objects.create(role=self.kitchen, title="Clean up", body="**Always**")
        fridge = Domain.objects.create(role=self.cook, text="The fridge")
        Policy.objects.create(role=self.cook, title="Labels", domain=fridge)
        result = self.gov("policies")
        self.assertIn("Clean up", result.output)
        self.assertIn("Cook (Kitchen)", result.output)
        self.assertIn(
            "Labels", self.gov("policies", "--circle", self.kitchen.pk).output
        )
        result = self.gov("policies", "show", Policy.objects.get(title="Labels").pk)
        self.assertIn("The fridge", result.output)

    def test_domains(self):
        from governance.roles.models import Domain, Policy

        Domain.objects.create(role=self.kitchen, text="The kitchen")
        fridge = Domain.objects.create(role=self.cook, text="The fridge")
        Policy.objects.create(role=self.cook, title="Labels", domain=fridge)
        result = self.gov("domains")
        self.assertIn("The kitchen", result.output)
        self.assertIn("Cook (Kitchen)", result.output)
        self.assertIn("Labels", result.output)
        result = self.gov("domains", "--circle", self.kitchen.pk)
        self.assertIn("The fridge", result.output)  # Also the circle's roles

    def test_export(self):
        result = self.gov("export")
        self.assertIn("Kitchen", result.output)
        self.assertIn("Cooking soup", result.output)
        self.assertNotIn("Ada", result.output)  # Personal data when asked for
        self.assertIn("Ada", self.gov("export", "--with-people").output)
        path = self.directory / "governance.md"
        self.gov("export", "--output", path)
        self.assertIn("Cooking soup", path.read_text())

    def test_role_context(self):
        """What affects a role from outside, per circle containing it"""
        Policy.objects.create(role=self.kitchen, title="Tea time", body="At four")
        Domain.objects.create(role=self.cook, text="The knives")
        pantry = Role.objects.create(name="Pantry", circle=self.kitchen, is_circle=True)
        shelf = Role.objects.create(name="Shelf", circle=pantry)
        result = self.gov("roles", "context", shelf.pk)
        self.assertIn("Kitchen", result.output)
        self.assertIn("Policy Tea time", result.output)
        self.assertIn("Domain: The knives", result.output)
        circles = json.loads(self.gov("roles", "context", shelf.pk, "--json").output)
        self.assertEqual([c["name"] for c in circles], ["Kitchen", "Pantry"])
        self.assertEqual(circles[0]["policies"][0]["body"], "At four")

    def test_constitution(self):
        self.assertIn("# **Holacracy Constitution**", self.gov("constitution").output)
        result = self.gov("constitution", "--language", "de")
        self.assertIn("# **Holacracy Verfassung**", result.output)

    def test_filling_roles(self):
        """Roles filled without being assigned (1.4.2, 5.3.6) are yours, the
        roles' and the meetings' Role Leads say as what"""
        Assignment.objects.create(
            role=self.kitchen.roles.get(core_role="lead"), user=self.ada
        )
        waiter = Role.objects.create(name="Waiter", circle=self.kitchen)
        me = json.loads(self.gov("me", "--json").output)
        mine = {role["id"]: role["filled_as"] for role in me["roles"]}
        self.assertEqual((mine[self.cook.pk], mine[waiter.pk]), (None, "lead"))
        self.assertRegex(self.gov("me").output, r"Waiter\s+as Circle Lead")

        role = json.loads(self.gov("roles", "show", waiter.pk, "--json").output)
        self.assertEqual(
            [(lead["name"], lead["filled_as"]) for lead in role["role_leads"]],
            [("Ada", "lead")],
        )
        self.assertRegex(
            self.gov("roles", "show", waiter.pk).output, r"Ada\s+as Circle Lead"
        )

        meeting = Meeting.objects.create(
            circle=self.kitchen, kind=Meeting.TACTICAL, started_at=timezone.now()
        )
        AgendaItem.objects.create(
            meeting=meeting,
            label="Trays",
            outcome=f"@[Waiter](role:{waiter.pk}): trays",
        )
        data = json.loads(self.gov("meetings", "show", meeting.pk, "--json").output)
        [mentioned] = data["items"][0]["roles"]
        self.assertEqual(
            [(lead["name"], lead["filled_as"]) for lead in mentioned["role_leads"]],
            [("Ada", "lead")],
        )
        self.assertIn(
            "@Waiter: Ada <ada@example.com> (as Circle Lead)",
            self.gov("meetings", "show", meeting.pk).output,
        )

    def test_meetings(self):
        """A tactical meeting's outcomes with the people filling the roles
        they mention, the tasks already linked, the circle's links: what
        the governance-tactical skill turns into tasks"""
        bob = User.objects.create_user("bob@example.com", full_name="Bob")
        Link.objects.create(
            role=self.kitchen, title="Projects", url="https://tasks.example.com/1"
        )
        meeting = Meeting.objects.create(
            circle=self.kitchen,
            kind=Meeting.TACTICAL,
            started_at=timezone.now() - dt.timedelta(hours=2),
            ended_at=timezone.now() - dt.timedelta(hours=1),
            secretary=bob,
            minutes="Short one",
        )
        meeting.attendees.add(self.ada, bob)
        AgendaItem.objects.create(
            meeting=meeting,
            label="Knives",
            owner=bob,
            outcome=f"@[Old name](role:{self.cook.pk}): new knives are bought",
            is_completed=True,
        )
        AgendaItem.objects.create(
            meeting=meeting,
            label="Menu",
            owner=self.ada,
            outcome="The winter menu is printed",
            link="https://tasks.example.com/todos/2",
        )
        AgendaItem.objects.create(meeting=meeting, label="Just news", owner=bob)
        Meeting.objects.create(
            circle=self.kitchen, kind=Meeting.GOVERNANCE, started_at=timezone.now()
        )

        result = self.gov("meetings", "--circle", self.kitchen.pk, "--kind", "tactical")
        self.assertIn("tactical meeting Kitchen", result.output)
        self.assertNotIn("governance meeting", result.output)
        self.assertEqual(
            [m["outcomes"] for m in json.loads(self.gov("meetings", "--json").output)],
            [0, 2],  # Newest first
        )

        result = self.gov("meetings", "show", meeting.pk)
        self.assertIn("@Cook: new knives are bought", result.output)
        self.assertIn("@Cook: Ada <ada@example.com>", result.output)
        self.assertIn("https://tasks.example.com/todos/2", result.output)
        self.assertIn("Kitchen: Projects", result.output)
        self.assertIn("Short one", result.output)

        data = json.loads(self.gov("meetings", "show", meeting.pk, "--json").output)
        knives, menu, news = data["items"]
        self.assertEqual(knives["owner"]["email"], "bob@example.com")
        self.assertEqual(
            [(r["id"], [p["email"] for p in r["role_leads"]]) for r in knives["roles"]],
            [(self.cook.pk, ["ada@example.com"])],
        )
        self.assertEqual(menu["roles"], [])
        self.assertEqual((news["outcome"], news["link"]), ("", ""))
        self.assertEqual(data["links"][0]["url"], "https://tasks.example.com/1")
        self.assertEqual(data["secretary"], "Bob")

    def test_backup(self):
        """Printed, or a file per role written into a directory; the people
        only when asked for"""
        data = json.loads(self.gov("backup").output)
        self.assertIn("Cook", [role["name"] for role in data["roles"]])
        self.assertNotIn("people", data)
        directory = self.directory / "backup"
        self.gov("backup", directory, "--with-people")
        cook = directory / "roles" / f"{self.cook.pk}.json"
        self.assertEqual(json.loads(cook.read_text())["name"], "Cook")
        self.assertIn("ada@example.com", (directory / "people.json").read_text())
        self.assertEqual(json.loads((directory / "meetings.json").read_text()), [])
        markdown = (directory / "governance.md").read_text()
        self.assertIn("Cooking soup", markdown)
        self.assertIn("Ada", markdown)  # With the people
        # Files by ID: a renamed role keeps its file. Each run replaces the
        # files, the people go when not asked for
        (directory / "roles" / "999.json").write_text("{}")
        Role.objects.filter(pk=self.cook.pk).update(name="Chef")
        self.gov("backup", directory)
        self.assertEqual(json.loads(cook.read_text())["name"], "Chef")
        self.assertFalse((directory / "roles" / "999.json").exists())
        self.assertFalse((directory / "people.json").exists())
        self.assertNotIn("Ada", (directory / "governance.md").read_text())

    def test_tokens_and_logout(self):
        """gov tokens lists and revokes tokens, gov logout revokes gov's own"""
        laptop, _secret = APIToken.create_for(
            user=self.ada, title="Laptop", access="write"
        )
        result = self.gov("tokens")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Laptop", result.output)
        self.assertRegex(result.output, r"\*\d+ +Tests")

        current, secret = APIToken.create_for(
            user=self.ada, title="Current", access="write"
        )
        result = self.gov("tokens", "delete", current.pk, laptop.pk, token=secret)
        self.assertEqual(result.exit_code, 0, result.output)
        # The token gov uses goes last
        self.assertEqual(
            result.output,
            f"Revoked Laptop ({laptop.pk}).\n"
            f"Revoked Current ({current.pk}). Logged out from http://testserver.\n",
        )
        self.assertFalse(
            APIToken.objects.filter(pk__in=[laptop.pk, current.pk]).exists()
        )
        self.assertNotIn("testserver", gov.core.CONFIG.read_text())

        # Read only tokens log out too
        _token, secret = APIToken.create_for(
            user=self.ada, title="Agent", access="read"
        )
        result = self.gov("logout", token=secret)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Logged out from http://testserver.", result.output)
        self.assertFalse(APIToken.objects.filter(title="Agent").exists())
        self.assertNotIn("testserver", gov.core.CONFIG.read_text())

        # Unreachable: forgotten anyway, but the token is still valid
        token, secret = APIToken.create_for(user=self.ada, title="Agent", access="read")
        with patch.object(
            gov.core.requests,
            "request",
            side_effect=gov.core.requests.ConnectionError("Unreachable"),
        ):
            result = self.gov("logout", token=secret)
        self.assertEqual(result.exit_code, 1)
        self.assertIn("couldn't revoke the token", result.output)
        self.assertNotIn("testserver", gov.core.CONFIG.read_text())
        self.assertTrue(APIToken.objects.filter(pk=token.pk).exists())

    def test_token_from_the_environment(self):
        """GOVERNANCE_URL and GOVERNANCE_TOKEN need no login, e.g. for the
        daily backup on a server"""
        _token, token = APIToken.create_for(
            user=self.ada, title="Backup", access="read"
        )
        result = CliRunner().invoke(
            gov.cli,
            ["backup"],
            env={"GOVERNANCE_URL": "http://testserver", "GOVERNANCE_TOKEN": token},
        )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Cook", result.output)

    def test_moved_installation(self):
        """Installations redirecting permanently to another host over HTTPS
        move in the configuration: following the redirect would drop the
        token (requests does for other hosts), each request a 401"""
        _token, token = APIToken.create_for(
            user=self.ada, title="Tests", access="write"
        )
        gov.core.write_config({
            "current": "https://old.example",
            "installations": {"https://old.example": {"token": token}},
        })
        moved = {"https://old.example": "https://new.example"}

        def request(method, url, **kwargs):
            parts = urllib.parse.urlsplit(url)
            if new := moved.get(f"{parts.scheme}://{parts.netloc}"):
                response = HttpResponsePermanentRedirect(f"{new}{parts.path}")
                return Response(response)
            return self.request(method, url, **kwargs)

        with patch.object(gov.core.requests, "request", request):
            result = CliRunner().invoke(gov.cli, ["me"], env={"GOV_DEBUG": "1"})
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Ada", result.output)
            self.assertIn("moved to https://new.example", result.output)
            config = gov.core.read_config()
            self.assertEqual(config["current"], "https://new.example")
            self.assertEqual(
                config["installations"], {"https://new.example": {"token": token}}
            )

            # Not to HTTP
            moved["https://new.example"] = "http://insecure.example"
            result = CliRunner().invoke(gov.cli, ["me"], env={"GOV_DEBUG": "1"})
            self.assertEqual(result.exit_code, 1)
            self.assertEqual(gov.core.read_config()["current"], "https://new.example")

            # Logging out too, from the new URL
            del moved["https://new.example"]
            gov.core.write_config({
                "current": "https://old.example",
                "installations": {"https://old.example": {"token": token}},
            })
            result = CliRunner().invoke(gov.cli, ["logout"], env={"GOV_DEBUG": "1"})
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Logged out from https://new.example.", result.output)
            self.assertFalse(APIToken.objects.filter(title="Tests").exists())
            self.assertEqual(gov.core.read_config()["installations"], {})

    def complete(self, args, incomplete):
        self.gov("me")  # Stores a token
        with patch.dict("os.environ", {"GOVERNANCE_URL": "http://testserver"}):
            completions = ShellComplete(gov.cli, {}, "gov", "_GOV_COMPLETE")
            return [
                (item.value, item.help)
                for item in completions.get_completions(args, incomplete)
            ]

    def test_completion(self):
        """IDs are completed with their names, also from a part of the name"""
        kitchen = (str(self.kitchen.pk), "Kitchen")
        self.assertIn(kitchen, self.complete(["circles", "show"], ""))
        self.assertEqual(self.complete(["circles", "show"], "kitch"), [kitchen])
        self.assertEqual(
            self.complete(["proposals", "create", "--role"], ""),
            [(str(self.cook.pk), "Cook (Kitchen)")],
        )
        self.assertIn(
            (str(self.cook.pk), "Cook (Kitchen)"),
            self.complete(["roles", "show"], "co"),
        )
        # Cached: a renamed circle shows up the next day
        Role.objects.filter(pk=self.kitchen.pk).update(name="Galley")
        self.assertEqual(self.complete(["circles", "show"], "kitch"), [kitchen])

    def test_bash_completion(self):
        """Bash has no descriptions: they're listed with the IDs when there
        are several, a single one is only the ID which bash inserts"""
        self.gov("me")  # Stores a token

        def complete(words):
            env = {
                "GOVERNANCE_URL": "http://testserver",
                "COMP_WORDS": words,
                "COMP_CWORD": str(len(words.split(" ")) - 1),
            }
            with patch.dict("os.environ", env):
                bash = get_completion_class("bash")(gov.cli, {}, "gov", "_GOV_COMPLETE")
                return bash.complete().splitlines()

        self.assertEqual(
            complete("gov circles show kitch"), [f"plain,{self.kitchen.pk}"]
        )
        listed = complete("gov roles show ")
        self.assertGreater(len(listed), 1)
        cook = next(line for line in listed if line.endswith("  -- Cook (Kitchen)"))
        self.assertEqual(cook.split()[0], f"plain,{self.cook.pk}")

    def test_skills(self):
        """Linking the skills into Claude Code's skills, replacing stale links
        and leaving directories of their own alone"""
        skills = self.directory / "claude" / "skills"
        ours = Path(gov.skills.__file__).parent
        skills.mkdir(parents=True)
        # Linked from an environment uv removed, a skill gov doesn't have
        # anymore, somebody's own skill and somebody's own directory
        gone = self.directory / "old" / "gov" / "skills"
        (skills / "governance-review").symlink_to(gone / "governance-review")
        (skills / "governance-gone").symlink_to(gone / "governance-gone")
        (skills / "mine").symlink_to(self.directory)
        (skills / "governance-tactical").mkdir()

        with patch.dict("os.environ", {"CLAUDE_CONFIG_DIR": str(skills.parent)}):
            result = self.gov("skills", "list")
            self.assertIn("governance-proposal", result.output)
            self.assertIn("not linked", result.output)
            self.assertIn("gov skills install", result.output)

            result = self.gov("skills", "install")
            self.assertIn("Linked governance-proposal.", result.output)
            self.assertIn("Linked governance-review.", result.output)
            self.assertIn("Removed governance-gone.", result.output)
            self.assertIn("governance-tactical is a directory", result.output)
            self.assertEqual(
                (skills / "governance-review").readlink(), ours / "governance-review"
            )
            self.assertTrue((skills / "governance-proposal" / "SKILL.md").exists())
            self.assertFalse((skills / "governance-gone").is_symlink())
            self.assertTrue((skills / "mine").is_symlink())

            # Nothing to do the second time
            result = self.gov("skills", "install")
            self.assertNotIn("Linked", result.output)

            data = json.loads(self.gov("skills", "list", "--json").output)
            states = {skill["name"]: skill["state"] for skill in data}
            self.assertEqual(states["governance-proposal"], "linked")
            self.assertEqual(states["governance-tactical"], "a directory of its own")

            self.gov("skills", "uninstall")
            self.assertEqual(
                sorted(path.name for path in skills.iterdir()),
                ["governance-tactical", "mine"],
            )
