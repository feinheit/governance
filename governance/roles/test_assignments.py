import datetime as dt

import time_machine
from django.test import TestCase

from governance.accounts.models import User
from governance.roles.models import Assignment, Role
from governance.roles.permissions import can_assign


@time_machine.travel(dt.datetime(2026, 12, 1, 12), tick=False)
class AssignmentsTest(TestCase):
    def setUp(self):
        self.ada = User.objects.create_user("ada@example.com", full_name="Ada")
        self.bob = User.objects.create_user("bob@example.com", full_name="Bob")
        self.eve = User.objects.create_user("eve@example.com", full_name="Eve")
        self.anchor = Role.objects.create(name="Example Ltd", is_circle=True)
        self.anchor.create_core_roles()
        self.kitchen = Role.objects.create(
            name="Kitchen", is_circle=True, circle=self.anchor
        )
        self.kitchen.create_core_roles()
        self.cook = Role.objects.create(name="Cook", circle=self.kitchen)
        self.anchor_lead = self.anchor.roles.get(core_role="lead")
        self.kitchen_lead = self.kitchen.roles.get(core_role="lead")
        # Ada leads the anchor circle, Bob the kitchen
        Assignment.objects.create(role=self.anchor_lead, user=self.ada)
        Assignment.objects.create(role=self.kitchen_lead, user=self.bob)
        Assignment.objects.create(role=self.kitchen, user=self.bob)

    def test_permissions(self):
        secretary = self.kitchen.roles.get(core_role="secretary")
        self.assertTrue(can_assign(self.bob, self.cook))
        self.assertFalse(can_assign(self.ada, self.cook))  # Not her circle
        self.assertFalse(can_assign(self.bob, secretary))  # Elected
        # The Secretary stands in for the Circle Lead
        Assignment.objects.create(role=secretary, user=self.eve)
        self.assertTrue(can_assign(self.eve, self.cook))
        self.assertFalse(can_assign(self.bob, self.kitchen))  # A circle
        # The super-circle's Circle Lead assigns the sub-circle's
        self.assertTrue(can_assign(self.ada, self.kitchen_lead))
        self.assertFalse(can_assign(self.bob, self.kitchen_lead))
        # Only admins assign the anchor circle's Circle Lead
        self.assertFalse(can_assign(self.ada, self.anchor_lead))
        self.eve.is_admin = True
        self.assertTrue(can_assign(self.eve, self.anchor_lead))
        self.assertTrue(can_assign(self.eve, self.cook))

        self.client.force_login(self.ada)
        self.assertNotContains(self.client.get(f"/roles/{self.cook.pk}/"), "Assign")
        self.assertEqual(
            self.client.get(f"/roles/{self.cook.pk}/assignments/").status_code, 403
        )

    def test_assign_and_remove(self):
        self.client.force_login(self.bob)
        self.assertContains(
            self.client.get(f"/roles/{self.cook.pk}/"),
            f'href="/roles/{self.cook.pk}/assignments/"',
        )
        url = f"/roles/{self.cook.pk}/assignments/"
        response = self.client.post(url, {"user": self.eve.pk, "focus": "Soup"})
        self.assertRedirects(response, url)
        assignment = Assignment.objects.get(role=self.cook)
        self.assertEqual(
            (assignment.user, assignment.focus, assignment.starts_on),
            (self.eve, "Soup", dt.date(2026, 12, 1)),
        )
        self.assertContains(self.client.get(url), "Soup")

        # The same person with the same focus again
        response = self.client.post(url, {"user": self.eve.pk, "focus": "Soup"})
        self.assertContains(response, "already holds this role")

        response = self.client.post(
            f"/assignments/{assignment.pk}/", {"user": self.ada.pk, "focus": "Salad"}
        )
        self.assertRedirects(response, url)
        assignment.refresh_from_db()
        # The person stays, only the focus changes
        self.assertEqual((assignment.user, assignment.focus), (self.eve, "Salad"))

        # Removed on the day it started: a mistake, nothing to keep
        self.client.post(f"/assignments/{assignment.pk}/end/")
        self.assertFalse(Assignment.objects.filter(role=self.cook).exists())

        assignment = Assignment.objects.create(
            role=self.cook, user=self.eve, starts_on=dt.date(2026, 1, 1)
        )
        self.client.post(f"/assignments/{assignment.pk}/end/")
        assignment.refresh_from_db()
        self.assertEqual(assignment.ends_on, dt.date(2026, 12, 1))
        self.assertEqual(
            self.client.get(f"/assignments/{assignment.pk}/").status_code, 404
        )

    def test_circle_lead(self):
        """The circle's role follows its Circle Lead"""
        self.client.force_login(self.ada)
        old = Assignment.objects.get(role=self.kitchen_lead)
        Assignment.objects.filter(role__in=[self.kitchen_lead, self.kitchen]).update(
            starts_on=dt.date(2026, 1, 1)
        )
        self.client.post(
            f"/roles/{self.kitchen_lead.pk}/assignments/", {"user": self.eve.pk}
        )
        self.client.post(f"/assignments/{old.pk}/end/")
        self.assertEqual(
            list(
                Assignment.objects
                .current()
                .filter(role=self.kitchen)
                .values_list("user", flat=True)
            ),
            [self.eve.pk],
        )
        self.assertEqual(
            Assignment.objects.get(role=self.kitchen, user=self.bob).ends_on,
            dt.date(2026, 12, 1),
        )

    def test_circle_rep_isnt_circle_lead(self):
        """The Circle Rep isn't assigned as Circle Lead of the circle (5.1.1)"""
        Assignment.objects.create(
            role=self.kitchen.roles.get(core_role="rep"), user=self.eve
        )
        self.client.force_login(self.ada)
        response = self.client.post(
            f"/roles/{self.kitchen_lead.pk}/assignments/", {"user": self.eve.pk}
        )
        self.assertContains(response, "A Circle Lead can&#x27;t be the Circle Rep.")
        self.assertFalse(
            Assignment.objects.filter(role=self.kitchen_lead, user=self.eve).exists()
        )
