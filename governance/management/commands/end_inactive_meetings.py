from django.core.management import BaseCommand

from governance.accounts.middleware import set_user_name
from governance.meetings.activity import end_inactive_meetings


class Command(BaseCommand):
    help = (
        "Hourly: ends the meetings inactive for hours and sends their outputs,"
        " fairy_tasks only runs at night"
    )

    def handle(self, **options):
        set_user_name("Fairy tasks")
        end_inactive_meetings()
