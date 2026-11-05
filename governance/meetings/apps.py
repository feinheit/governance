from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class Config(AppConfig):
    name = "governance.meetings"
    verbose_name = _("meetings")

    def ready(self):
        from governance.meetings.activity import connect

        connect()
