import datetime as dt

from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from governance.accounts.models import APIToken, User, prune_api_tokens
from governance.meetings.models import Meeting
from governance.proposals.models import Proposal
from governance.roles.models import Accountability, Assignment, Role


class APITest(TestCase):
    def setUp(self):
        self.ada = User.objects.create_user("ada@example.com", full_name="Ada")
        self.bob = User.objects.create_user("bob@example.com", full_name="Bob")
        self.kitchen = Role.objects.create(
            name="Kitchen", is_circle=True, purpose="Food", async_acceptance_days=4
        )
        self.kitchen.create_core_roles()
        self.cook = Role.objects.create(name="Cook", circle=self.kitchen)
        Accountability.objects.create(role=self.cook, text="Cooking soup")
        Assignment.objects.create(role=self.cook, user=self.ada, focus="Soup")
        _token, self.secret = APIToken.create_for(
            user=self.ada, title="Script", access="write"
        )
        _token, self.read_secret = APIToken.create_for(
            user=self.ada, title="Reader", access="read"
        )

    def api(self, method, url, data=None, secret=None):
        return getattr(self.client, method)(
            url,
            data=data,
            content_type="application/json",
            headers={"authorization": f"Bearer {secret or self.secret}"},
        )

    def test_tokens_extend_themselves(self):
        """A token in use stays valid, one nobody uses expires after 30 days"""
        import datetime as dt

        import time_machine
        from django.utils import timezone

        token = APIToken.objects.for_secret(self.read_secret)
        start = timezone.now()
        self.assertEqual((token.expires_at - start).days, 29)
        with time_machine.travel(start + dt.timedelta(days=20)):
            self.assertEqual(
                self.api("get", "/api/me/", secret=self.read_secret).status_code, 200
            )
        with time_machine.travel(start + dt.timedelta(days=45)):
            self.assertEqual(
                self.api("get", "/api/me/", secret=self.read_secret).status_code, 200
            )
        with time_machine.travel(start + dt.timedelta(days=80)):
            self.assertEqual(
                self.api("get", "/api/me/", secret=self.read_secret).status_code, 401
            )

    def test_refused_changes_dont_extend_tokens(self):
        """Changes a read only token may not make aren't a use of it"""
        response = self.api("post", "/api/proposals/", {}, secret=self.read_secret)
        self.assertEqual(response.status_code, 403)
        token = APIToken.objects.get(title="Reader")
        self.assertIsNone(token.last_used_at)
        self.api("get", "/api/me/", secret=self.read_secret)
        token.refresh_from_db()
        self.assertIsNotNone(token.last_used_at)

    def test_tokens_page(self):
        self.assertRedirects(
            self.client.get("/accounts/api-tokens/"),
            "/accounts/login/?next=/accounts/api-tokens/",
            fetch_redirect_response=False,
        )
        self.client.force_login(self.bob)
        response = self.client.post(
            "/accounts/api-tokens/", {"title": "Mine", "access": "read"}
        )
        self.assertContains(response, "gov_")
        token = self.bob.api_tokens.get()
        # Asked first, e.g. in a modal; only one's own
        url = f"/accounts/api-tokens/{token.pk}/delete/"
        self.assertContains(self.client.get(url), "Delete the API token Mine?")
        self.client.force_login(self.ada)
        self.assertEqual(self.client.post(url).status_code, 404)
        self.client.force_login(self.bob)
        self.client.post(url)
        self.assertFalse(self.bob.api_tokens.exists())

        APIToken.objects.update(expires_at=timezone.now() - dt.timedelta(days=100))
        prune_api_tokens()
        self.assertFalse(APIToken.objects.exists())

    def test_read(self):
        self.assertEqual(self.client.get("/api/circles/").status_code, 401)
        self.assertEqual(
            self.api("get", "/api/circles/", secret="nonsense").status_code, 401
        )
        response = self.api("get", "/api/circles/", secret=self.read_secret)
        self.assertEqual(
            response.json(),
            [
                {
                    "id": self.kitchen.pk,
                    "name": "Kitchen",
                    "circle_id": None,
                    "depth": 0,
                    "purpose": "Food",
                    "url": f"{settings.BASE_URL}/roles/{self.kitchen.pk}/",
                }
            ],
        )
        data = self.api("get", f"/api/roles/{self.cook.pk}/").json()
        self.assertEqual(data["accountabilities"][0]["text"], "Cooking soup")
        self.assertEqual(data["role_leads"][0]["focus"], "Soup")
        data = self.api("get", f"/api/roles/{self.kitchen.pk}/").json()
        self.assertEqual(len(data["roles"]), 4)
        self.assertIn(
            {"id": self.cook.pk, "name": "Cook", "circle": "Kitchen"},
            self.api("get", "/api/roles/").json(),
        )
        data = self.api("get", "/api/search/?q=SOUP").json()
        self.assertEqual(data["accountabilities"][0]["text"], "Cooking soup")

        # The session works too
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get("/api/circles/").status_code, 200)

    def test_texts_the_proposal_adds(self):
        """Instructions changing or removing a text the proposal adds apply
        to it, not a server error"""
        cook = self.cook.pk
        response = self.api(
            "post",
            "/api/proposals/",
            {
                "circle_id": self.kitchen.pk,
                "role_id": self.cook.pk,
                "tension": "Soups",
                "instructions": [
                    {
                        "op": "add",
                        "path": f"/roles/{cook}/accountabilities/n1",
                        "value": "Soup",
                    },
                    {
                        "op": "replace",
                        "path": f"/roles/{cook}/accountabilities/n1",
                        "value": "Soups",
                    },
                    {"op": "add", "path": f"/roles/{cook}/domains/n2", "value": "Pot"},
                    {"op": "remove", "path": f"/roles/{cook}/domains/n2"},
                ],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["problems"], [])

    def test_proposals(self):
        # Read only tokens don't change anything
        response = self.api(
            "post",
            "/api/proposals/",
            {
                "circle_id": self.kitchen.pk,
                "role_id": self.cook.pk,
                "tension": "No bread",
            },
            secret=self.read_secret,
        )
        self.assertEqual(response.status_code, 403)

        response = self.api(
            "post",
            "/api/proposals/",
            {
                "circle_id": self.kitchen.pk,
                "role_id": self.cook.pk,
                "tension": "No bread",
                "instructions": [
                    {"op": "add", "path": "/roles/n1"},
                    {"op": "add", "path": "/roles/n1/name", "value": "Baker"},
                    {
                        "op": "replace",
                        "path": f"/roles/{self.cook.pk}/name",
                        "original_value": "Cuisinier",
                        "value": "Chef",
                    },
                ],
            },
        )
        data = response.json()
        self.assertEqual(data["status"], "draft")
        self.assertEqual(
            data["names"], {"roles/n1": "Baker", f"roles/{self.cook.pk}": "Cook"}
        )
        self.assertEqual(
            data["problems"],
            ["Cook: name has been changed since the proposal was drafted."],
        )
        pk = data["id"]
        response = self.api("post", f"/api/proposals/{pk}/publish/")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(response.json()["problems"]), 1)

        response = self.api(
            "patch",
            f"/api/proposals/{pk}/",
            {"instructions": [{"op": "jump", "path": "/roles/1"}]},
        )
        self.assertEqual(response.status_code, 400)
        response = self.api(
            "patch",
            f"/api/proposals/{pk}/",
            {
                "tension": "No bread at all",
                "instructions": [
                    {"op": "add", "path": "/roles/n1"},
                    {"op": "add", "path": "/roles/n1/name", "value": "Baker"},
                ],
            },
        )
        self.assertEqual(response.json()["problems"], [])
        # Somebody else to ask, otherwise publishing adopts it right away
        Assignment.objects.create(
            role=Role.objects.create(name="Waiter", circle=self.kitchen),
            user=User.objects.create_user("eve@example.com"),
        )
        data = self.api("post", f"/api/proposals/{pk}/publish/").json()
        self.assertEqual(data["status"], "published")
        self.assertIsNotNone(data["deadline"])
        self.assertEqual(
            self.api("get", f"/api/proposals/?circle_id={self.kitchen.pk}").json()[0][
                "id"
            ],
            pk,
        )

        # Bob isn't a member and doesn't see Ada's drafts
        Proposal.objects.create(
            circle=self.kitchen,
            proposer=self.ada,
            tension="Secret",
            created_at=timezone.now(),
        )
        _token, bob_secret = APIToken.create_for(
            user=self.bob, title="Bob", access="write"
        )
        self.assertEqual(
            len(self.api("get", "/api/proposals/", secret=bob_secret).json()), 1
        )
        response = self.api(
            "post",
            "/api/proposals/",
            {"circle_id": self.kitchen.pk, "role_id": self.cook.pk, "tension": "Hi"},
            secret=bob_secret,
        )
        self.assertEqual(response.status_code, 403)
        response = self.api(
            "patch", f"/api/proposals/{pk}/", {"tension": "Mine"}, secret=bob_secret
        )
        self.assertEqual(response.status_code, 403)

    def test_proposal_inside_a_role(self):
        """Role Leads add roles inside their role (1.3.1), also through the API
        like on the role's page"""
        response = self.api(
            "post",
            "/api/proposals/",
            {
                "circle_id": self.cook.pk,
                "role_id": self.cook.pk,
                "tension": "Too much to do",
                "instructions": [
                    {"op": "add", "path": "/roles/n1"},
                    {"op": "add", "path": "/roles/n1/name", "value": "Sous"},
                ],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["problems"], [])

    def test_malformed_instructions(self):
        """Instructions of the wrong shape are problems, not errors"""
        response = self.api(
            "post",
            "/api/proposals/",
            {
                "circle_id": self.kitchen.pk,
                "role_id": self.cook.pk,
                "tension": "No bread",
                "instructions": [{"op": "move", "path": "/roles/1", "from": 5}],
            },
        )
        self.assertEqual(response.status_code, 400)
        # Values are texts: anything else would be saved as its repr
        path = f"/roles/{self.cook.pk}/name"
        for instruction in [
            {"op": "replace", "path": path, "value": ["Baker"]},
            {"op": "replace", "path": path, "value": "Baker", "original_value": 5},
        ]:
            with self.subTest(instruction=instruction):
                response = self.api(
                    "post",
                    "/api/proposals/",
                    {
                        "circle_id": self.kitchen.pk,
                        "role_id": self.cook.pk,
                        "tension": "No bread",
                        "instructions": [instruction],
                    },
                )
                self.assertEqual(response.status_code, 400)

    def test_only_proposers_change_proposals(self):
        """The secretary amends in a running meeting's page, not through the
        API: scripts only change their user's own drafts"""
        meeting = Meeting.objects.create(
            circle=self.kitchen,
            kind=Meeting.GOVERNANCE,
            started_at=timezone.now(),
            secretary=self.ada,
        )
        proposal = Proposal.objects.create(
            circle=self.kitchen,
            role=self.cook,
            proposer=self.bob,
            tension="Soup",
            status=Proposal.IN_MEETING,
            meeting=meeting,
            created_at=timezone.now(),
        )
        response = self.api(
            "patch", f"/api/proposals/{proposal.pk}/", {"tension": "Stew"}
        )
        self.assertEqual(response.status_code, 403)
        proposal.refresh_from_db()
        self.assertEqual(proposal.tension, "Soup")

    def test_links(self):
        """Anybody manages the links of active roles, not with a read only
        token; the role's links come with it"""
        response = self.api(
            "post",
            f"/api/roles/{self.kitchen.pk}/links/",
            {"title": " Projects ", "url": "https://example.com/projects"},
        )
        self.assertEqual(response.status_code, 200)
        link = response.json()
        self.assertEqual(link["title"], "Projects")
        self.assertEqual(link["description"], "")
        self.api(
            "post",
            f"/api/roles/{self.kitchen.pk}/links/",
            {"title": "Board", "url": "https://example.com/board"},
        )
        role = self.api("get", f"/api/roles/{self.kitchen.pk}/").json()
        self.assertEqual(
            [item["title"] for item in role["links"]], ["Projects", "Board"]
        )

        response = self.api(
            "patch", f"/api/links/{link['id']}/", {"description": "To-dos"}
        )
        self.assertEqual(response.json()["description"], "To-dos")
        self.assertEqual(response.json()["url"], "https://example.com/projects")
        response = self.api("patch", f"/api/links/{link['id']}/", {"url": "nope"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("url", response.json()["detail"])

        response = self.api(
            "delete", f"/api/links/{link['id']}/", secret=self.read_secret
        )
        self.assertEqual(response.status_code, 403)
        response = self.api("delete", f"/api/links/{link['id']}/")
        self.assertEqual(response.json()["title"], "Projects")
        role = self.api("get", f"/api/roles/{self.kitchen.pk}/").json()
        self.assertEqual([item["title"] for item in role["links"]], ["Board"])

        Role.objects.filter(pk=self.cook.pk).update(archived_on=timezone.localdate())
        response = self.api(
            "post",
            f"/api/roles/{self.cook.pk}/links/",
            {"title": "Recipes", "url": "https://example.com/recipes"},
        )
        self.assertEqual(response.status_code, 403)
