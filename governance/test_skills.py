import re

import yaml
from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from governance.accounts.models import User
from governance.proposals.instructions import problems, validate_format
from governance.proposals.models import Proposal
from governance.roles.models import Assignment, Role


SKILLS = settings.BASE_DIR / "cli" / "skills"
SKILL = SKILLS / "governance-proposal" / "SKILL.md"


def gov_commands(text):
    """The words of the `gov` commands in a skill, up to the first argument
    in angle brackets or a redirection"""
    for line in re.findall(r"^\s*(gov [^\n#]*)", text, re.MULTILINE):
        yield [word for word in line.split() if word != "\\"]


class SkillTest(TestCase):
    def test_gov_commands(self):
        """The commands and options the skills use exist"""
        import gov

        paths = sorted(SKILLS.glob("*/SKILL.md"))
        self.assertGreaterEqual(len(paths), 2)
        for path in paths:
            for words in gov_commands(path.read_text()):
                with self.subTest(skill=path.parent.name, command=" ".join(words)):
                    command = gov.cli
                    rest = iter(words[1:])
                    for word in rest:
                        if word in {"<", "|"}:
                            break
                        if len(word) > 1 and word.startswith("-"):  # Not stdin
                            options = {
                                opt: param
                                for param in command.params
                                for opt in param.opts
                            }
                            self.assertIn(word, options)
                            if not options[word].is_flag:
                                next(rest)  # Its value
                        elif hasattr(command, "commands"):
                            # Groups take no arguments, only their commands
                            self.assertIn(word, command.commands)
                            command = command.commands[word]

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
