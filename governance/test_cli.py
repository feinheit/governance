import json
import tempfile
import urllib.parse
from pathlib import Path
from unittest.mock import patch

import gov
from click.shell_completion import ShellComplete
from click.testing import CliRunner
from django.test import Client, TestCase
from django.utils.translation import deactivate_all

from governance import cli_version
from governance.accounts.models import APIToken, User
from governance.proposals.models import Proposal
from governance.roles.models import Accountability, Assignment, Domain, Policy, Role


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

    def request(self, method, url, *, headers, timeout, params=None, json=None):
        path = urllib.parse.urlsplit(url).path
        if method == "GET":
            response = self.api_client.get(path, params, headers=headers)
        else:
            response = getattr(self.api_client, method.lower())(
                path, json, content_type="application/json", headers=headers
            )
        return Response(response)

    def gov(self, *args, access="write", input=None):
        _token, token = APIToken.create_for(user=self.ada, title="Tests", access=access)
        config = gov.core.read_config()
        config["installations"]["http://testserver"] = {"token": token}
        gov.core.write_config(config)
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
        self.assertIn("Nothing found.", self.gov("search", "nothing").output)

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
            **published, tension="Later", deadline=now + dt.timedelta(days=5)
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
