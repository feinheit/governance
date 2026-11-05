import re

import yaml
from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from governance.accounts.models import User
from governance.proposals.instructions import problems, validate_format
from governance.proposals.models import Proposal
from governance.roles.models import Assignment, Role


SKILL = settings.BASE_DIR / "cli" / "skills" / "governance-proposal" / "SKILL.md"


class SkillTest(TestCase):
    def test_proposal_examples(self):
        """The skill's examples of instructions are what the server takes"""
        text = SKILL.read_text()
        examples = yaml.safe_load(re.search(r"```yaml\n(.*?)```", text, re.DOTALL)[1])
        self.assertEqual(validate_format(examples), [])

        # The new role of the first example adopts without problems
        ada = User.objects.create_user("ada@example.com")
        kitchen = Role.objects.create(name="Kitchen", is_circle=True)
        kitchen.create_core_roles()
        cook = Role.objects.create(name="Cook", circle=kitchen)
        Assignment.objects.create(role=cook, user=ada)
        new_role = [i for i in examples if re.match(r"/roles/n1\b", i["path"])]
        proposal = Proposal.objects.create(
            circle=kitchen,
            role=cook,
            proposer=ada,
            tension="No bread",
            instructions=new_role,
            created_at=timezone.now(),
        )
        self.assertEqual(len(new_role), 5)
        self.assertEqual(problems(proposal), [])
