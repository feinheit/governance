from django.conf import settings
from django.contrib import admin
from django.shortcuts import redirect
from django.templatetags.static import static
from django.urls import include, path

from governance.accounts.views import cli_login
from governance.api import api
from governance.help import help_page
from governance.search import search


def favicon(request):
    """Browsers ask for /favicon.ico without looking at the page"""
    return redirect(static("governance/favicon.png"), permanent=True)


# Deleted drafts are explained to their proposer
handler404 = "governance.not_found.page_not_found"

urlpatterns = [
    path("favicon.ico", favicon),
    path("", include("governance.roles.urls")),
    path("", include("governance.proposals.urls")),
    path("", include("governance.history.urls")),
    path("", include("governance.meetings.urls")),
    path("search/", search, name="search"),
    path("help/", help_page, name="help"),
    path("help/<slug:page>/", help_page, name="help"),
    path("api/", api.urls),
    path("accounts/", include("governance.accounts.urls")),
    path("cli-login/", cli_login, name="cli_login"),
    path("admin/", admin.site.urls),
]

if settings.DEBUG:  # pragma: no cover
    from governance.not_found import preview

    # Django shows its own 404 page with DEBUG, this one previews ours
    urlpatterns.append(path("404/", preview))

if settings.DEBUG_TOOLBAR:  # pragma: no cover
    from debug_toolbar.toolbar import debug_toolbar_urls

    urlpatterns += debug_toolbar_urls()
