import datetime as dt

from django.core.management import BaseCommand
from django.utils import timezone

from governance.accounts.middleware import set_user_name
from governance.accounts.models import prune_api_tokens
from governance.history.update import update_changes
from governance.notifications import mails


class Command(BaseCommand):
    help = (
        "Daily tasks: the history's changes, pruning API tokens, reminders;"
        " adopting async proposals and ending meetings is hourly (hourly_tasks)"
    )

    def handle(self, **options):
        set_user_name("Fairy tasks")
        # Yesterday's late changes too
        update_changes(since=timezone.localdate() - dt.timedelta(days=1))
        prune_api_tokens()
        if timezone.localdate().weekday() == 0:  # Mondays
            mails.elections_due()
