from django.conf import settings
from django.db import connections
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.translation import activate


def set_user_name(user):
    """The user the audit log records for changes, a user or a name"""
    if not isinstance(user, str):
        user = f"user-{user.id}-{user.get_short_name()}"
    connections["default"].cursor().execute(
        "SET SESSION application_name TO %s", [user]
    )


def user_middleware(get_response):
    def middleware(request):
        if request.user.is_authenticated:
            set_user_name(request.user)
            if request.user.language:
                activate(request.user.language)
            return get_response(request)

        set_user_name("user-0-anonymous")
        if request.path.startswith(settings.LOGIN_REQUIRED_EXEMPT):
            return get_response(request)

        response = HttpResponseRedirect(reverse("login"))
        response.set_signed_cookie("next", request.get_full_path(), salt="next")
        return response

    return middleware
