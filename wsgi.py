import os
from pathlib import Path

from speckenv import read_speckenv


read_speckenv(Path(__file__).parent / ".env")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "governance.settings")

from django.core.wsgi import get_wsgi_application  # noqa: E402


application = get_wsgi_application()
