import datetime as dt

from django.core.management import BaseCommand
from django.utils import timezone

from governance.accounts.middleware import set_user_name
from governance.accounts.models import prune_api_tokens
from governance.history.update import update_changes
from governance.meetings.activity import end_inactive_meetings
from governance.notifications import mails
from governance.proposals.process import adopt_due_proposals


class Command(BaseCommand):
    help = (
        "Daily tasks: adopting async proposals, ending inactive meetings,"
        " the history's changes, reminders"
    )

    def handle(self, **options):
        set_user_name("Fairy tasks")
        adopt_due_proposals()
        end_inactive_meetings()
        # Yesterday's late changes too
        update_changes(since=timezone.localdate() - dt.timedelta(days=1))
        prune_api_tokens()
        if timezone.localdate().weekday() == 0:  # Mondays
            mails.elections_due()
