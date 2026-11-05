from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from governance.glassfrog.export import ApiExport
from governance.glassfrog.importer import import_glassfrog
from governance.roles.models import Role


class Command(BaseCommand):
    help = (
        "Imports GlassFrog: the whole history from a checkout of the fetcher's"
        " repository, or (with --api, or without a checkout) today's state from"
        " GlassFrog's API, added to the history in the database."
    )

    def add_arguments(self, parser):
        parser.add_argument("path", nargs="?", default=settings.GLASSFROG_EXPORT)
        parser.add_argument(
            "--api", action="store_true", help="Fetch today's state from the API"
        )

    def handle(self, *, path, api, **options):
        if api or not path:
            if not settings.GLASSFROG_TOKEN:
                raise CommandError(
                    "Pass the path of the export, set GLASSFROG_EXPORT or GLASSFROG_TOKEN."
                )
            if not Role.objects.exclude(glassfrog_id=None).exists():
                self.stderr.write(
                    "Warning: no earlier import, the history starts today."
                    " Import a checkout first to get the whole history."
                )
            export = ApiExport(settings.GLASSFROG_TOKEN)
        else:
            export = path
        import_glassfrog(export, log=self.stdout.write)
