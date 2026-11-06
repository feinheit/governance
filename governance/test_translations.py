from django.test import TestCase

from governance.accounts.models import User
from governance.roles.models import Role


class TranslationsTest(TestCase):
    def test_german(self):
        self.client.force_login(
            User.objects.create_user("ada@example.com", language="de")
        )
        circle = Role.objects.create(name="Kitchen", is_circle=True)
        circle.create_core_roles()
        response = self.client.get(circle.get_absolute_url())
        self.assertContains(response, "Kernrollen")
        self.assertContains(response, "Von den Circle Leads besetzt")
        # The core roles keep their names, like in GlassFrog and the handbook
        self.assertContains(response, "Secretary")
        lead = circle.roles.get(core_role="lead")
        self.assertContains(
            self.client.get(lead.get_absolute_url()), "weist die Rollen zu"
        )
        response = self.client.get("/search/", {"q": "nothing"})
        self.assertContains(response, "Nichts gefunden.")
