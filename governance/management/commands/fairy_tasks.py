from django.core.management import BaseCommand
from django.utils import timezone

from governance.accounts.middleware import set_user_name
from governance.accounts.models import prune_api_tokens
from governance.history.snapshots import take_snapshot
from governance.meetings.activity import end_inactive_meetings
from governance.notifications.mails import elections_due
from governance.proposals.process import adopt_due_proposals


class Command(BaseCommand):
    help = (
        "Daily tasks: adopting async proposals, ending inactive meetings,"
        " today's snapshot, reminders"
    )

    def handle(self, **options):
        set_user_name("Fairy tasks")
        adopt_due_proposals()
        end_inactive_meetings()
        take_snapshot()
        prune_api_tokens()
        if timezone.localdate().weekday() == 0:  # Mondays
            elections_due()
