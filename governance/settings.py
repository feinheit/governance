import sys
from pathlib import Path

from django.utils.translation import gettext_lazy as _
from speckenv import env
from speckenv_django import django_database_url, django_email_url


BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = env("SECRET_KEY", required=True)
DEBUG = env("DEBUG", default=bool({"runserver", "shell"}.intersection(sys.argv)))
TESTING = env("TESTING", default="test" in sys.argv)
LIVE = env("LIVE", default=False)
ALLOWED_HOSTS = env("ALLOWED_HOSTS", default=[])
# Redirects to the canonical domain (and to HTTPS), see django-canonical-domain
SECURE_SSL_HOST = env("SECURE_SSL_HOST", default=None)
SECURE_SSL_REDIRECT = env("SECURE_SSL_REDIRECT", default=False)
ADMINS = MANAGERS = [
    ("Matthias Kestenholz", "mk@feinheit.ch"),
    ("Fabian Germann", "fg@feinheit.ch"),
]
DEFAULT_FROM_EMAIL = SERVER_EMAIL = env(
    "DEFAULT_FROM_EMAIL", default="governance@feinheit.ch"
)

# Google sign-in, only for existing, active users
GOOGLE_CLIENT_ID = env("GOOGLE_CLIENT_ID", default="")
GOOGLE_CLIENT_SECRET = env("GOOGLE_CLIENT_SECRET", default=None)

# Links in mails
# The dev server of fl dev (AGENTS.md)
BASE_URL = env("BASE_URL", default="http://127.0.0.1:8000")

DEBUG_TOOLBAR = DEBUG and not TESTING

INSTALLED_APPS = [
    a
    for a in [
        "governance",
        "django.contrib.admin",
        "django.contrib.auth",
        "django.contrib.contenttypes",
        "django.contrib.sessions",
        "django.contrib.messages",
        "django.contrib.staticfiles",
        "django.contrib.postgres",
        "django.forms",
        "canonical_domain",
        "governance.accounts",
        "governance.audit",
        "governance.roles",
        "governance.proposals",
        "governance.meetings",
        "governance.history",
        "governance.notifications",
        "debug_toolbar" if DEBUG_TOOLBAR else "",
    ]
    if a
]

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["authlib.backends.EmailBackend"]
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "/"
# The API authenticates itself (tokens or the session)
LOGIN_REQUIRED_EXEMPT = ("/accounts/", "/api/", "/favicon", "/robots", "/static/")

MIDDLEWARE = [
    m
    for m in [
        "canonical_domain.middleware.canonical_domain",
        "django.middleware.security.SecurityMiddleware" if LIVE else "",
        "debug_toolbar.middleware.DebugToolbarMiddleware" if DEBUG_TOOLBAR else "",
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.middleware.common.CommonMiddleware",
        "django.middleware.locale.LocaleMiddleware",
        "django.middleware.csrf.CsrfViewMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
        "django.middleware.clickjacking.XFrameOptionsMiddleware",
        # Outside of user_middleware: its redirect to the login too
        "governance.modals.modal_middleware",
        "governance.accounts.middleware.user_middleware",
        "governance.cli_version.cli_version_middleware",
    ]
    if m
]

ROOT_URLCONF = "governance.urls"
WSGI_APPLICATION = "wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "governance" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.i18n",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "governance.modals.context",
            ],
        },
    }
]
FORM_RENDERER = "governance.forms.Renderer"

LOCALE_PATHS = [BASE_DIR / "conf" / "locale"]

DATABASES = {"default": django_database_url(env("DATABASE_URL", required=True))}
DATABASES["default"] |= {
    "ATOMIC_REQUESTS": True,
    "CONN_HEALTH_CHECKS": True,
    "CONN_MAX_AGE": 300,
    "DISABLE_SERVER_SIDE_CURSORS": True,
}
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

LANGUAGE_CODE = "de"
LANGUAGES = [("de", _("German")), ("en", _("English"))]
TIME_ZONE = "Europe/Zurich"
USE_I18N = True
USE_TZ = True
FORMAT_MODULE_PATH = ["governance.formats"]

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"
        if LIVE
        else "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "static"

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_AGE = 14 * 86400
SESSION_SAVE_EVERY_REQUEST = True
MESSAGE_STORAGE = "django.contrib.messages.storage.cookie.CookieStorage"

if LIVE:  # pragma: no cover
    SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000

EMAIL_URL = env("EMAIL_URL", default="console:" if DEBUG else "smtp:")
_email = django_email_url(EMAIL_URL)
MAILERS = {
    "default": {
        "BACKEND": _email["EMAIL_BACKEND"],
        "OPTIONS": {
            option: _email[setting]
            for option, setting in [
                ("host", "EMAIL_HOST"),
                ("port", "EMAIL_PORT"),
                ("username", "EMAIL_HOST_USER"),
                ("password", "EMAIL_HOST_PASSWORD"),
                ("use_tls", "EMAIL_USE_TLS"),
                ("use_ssl", "EMAIL_USE_SSL"),
            ]
            if _email[setting]
        },
    }
}

if DEBUG_TOOLBAR:  # pragma: no cover
    INTERNAL_IPS = ["127.0.0.1"]

# Errors in production, like Workbench (SENTRY_ENVIRONMENT is read by the SDK)
if SENTRY_DSN := env("SENTRY_DSN"):  # pragma: no cover
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(dsn=SENTRY_DSN, integrations=[DjangoIntegration()])

if TESTING:
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    # Tests check the English texts, test_translations the German ones
    LANGUAGE_CODE = "en"
