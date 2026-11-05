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
from governance.roles.models import Accountability, Assignment, Role


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
            name="Kitchen", is_circle=True, purpose="Food for everyone"
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
            call_command("fairy_tasks")
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
        self.assertIn("Ada", result.output)
        self.assertNotIn("Ada", self.gov("export", "--without-holders").output)
        path = self.directory / "governance.md"
        self.gov("export", "--output", path)
        self.assertIn("Cooking soup", path.read_text())

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
