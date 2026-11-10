from django.core.management import BaseCommand

from governance.accounts.middleware import set_user_name
from governance.meetings.activity import end_inactive_meetings
from governance.proposals.process import adopt_due_proposals


class Command(BaseCommand):
    help = (
        "Hourly: adopts the async proposals whose deadline passed, ends the"
        " meetings inactive for hours and sends their outputs"
    )

    def handle(self, **options):
        set_user_name("Fairy tasks")
        adopt_due_proposals()
        end_inactive_meetings()
