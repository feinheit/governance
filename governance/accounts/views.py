import re

from authlib.google import GoogleOAuth2Client
from django import forms
from django.conf import settings
from django.contrib import auth, messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import (
    activate,
    get_language,
    gettext,
    gettext as _,
    gettext_lazy,
)
from django.views.decorators.cache import never_cache

from governance import cli_version
from governance.accounts.models import API_TOKEN_LIFETIME, APIToken, User
from governance.forms import ModelForm, next_url


def _next_url(request):
    url = request.get_signed_cookie("next", default=None, salt="next")
    if url and url_has_allowed_host_and_scheme(url, allowed_hosts={request.get_host()}):
        return url
    return "/"


@never_cache
def login(request):
    if (
        settings.DEBUG
        and not settings.LIVE
        and (email := request.GET.get("force_login"))
    ) and (user := auth.authenticate(request, email=email)):
        auth.login(request, user)
        return redirect("/")
    if request.user.is_authenticated:
        return redirect("/")
    return render(request, "accounts/login.html")


@never_cache
def oauth2(request):
    auth_params = request.GET.dict()
    auth_params.setdefault("login_hint", request.COOKIES.get("login_hint", ""))
    client = GoogleOAuth2Client(request, authorization_params=auth_params)

    if not request.GET.get("code"):
        return redirect(client.get_authentication_url())

    try:
        user_data = client.get_user_data()
    except Exception:  # noqa: BLE001
        messages.error(request, _("Error while fetching user data. Please try again."))
        return redirect("login")

    email = (user_data.get("email") or "").lower()
    user = auth.authenticate(request, email=email)
    if user:
        auth.login(request, user)
        response = redirect(_next_url(request))
        response.delete_cookie("next")
        response.set_cookie("login_hint", user.email, max_age=180 * 86400)
        return response

    if User.objects.filter(email=email).exists():
        messages.error(
            request, _("The user with email address %s is inactive.") % email
        )
    else:
        messages.error(request, _("No user with email address %s found.") % email)
    response = redirect("login")
    response.delete_cookie("login_hint")
    return response


def logout(request):
    auth.logout(request)
    messages.success(request, _("You have been signed out."))
    response = redirect("login")
    response.delete_cookie("login_hint")
    return response


@never_cache
@login_required  # /accounts/ is exempt from the login middleware
def api_tokens(request):
    secret = None
    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        access = request.POST.get("access")
        if title and access in APIToken.Access.values:
            _token, secret = APIToken.create_for(
                user=request.user, title=title[:100], access=access
            )
    return render(
        request,
        "accounts/api_tokens.html",
        {
            "tokens": request.user.api_tokens.all(),
            "secret": secret,
            "days": API_TOKEN_LIFETIME.days,
            "access_choices": APIToken.Access.choices,
            "api_url": request.build_absolute_uri("/api/"),
            "cli_install": cli_version.INSTALL,
            "base_url": request.build_absolute_uri("/"),
        },
    )


@never_cache
@login_required
def api_token_delete(request, pk):
    """Deleting one's token, confirmed first (in a modal on the tokens page)"""
    token = get_object_or_404(request.user.api_tokens, pk=pk)
    if request.method == "POST":
        token.delete()
        messages.success(request, gettext("The API token has been deleted."))
        return redirect("api_tokens")
    return render(
        request,
        "generic/confirm.html",
        {
            "question": gettext("Delete the API token %(title)s?")
            % {"title": token.title},
            "help": gettext("Scripts and gov using it lose their access."),
            "submit_label": gettext("Delete"),
            "cancel_url": reverse("api_tokens"),
        },
    )


@never_cache
def cli_login(request):
    """Authorize the gov command line interface on this computer

    gov waits on a local port for the token. The login middleware makes sure
    that the user is signed in (outside /accounts/, it brings people back
    here after signing in)."""
    try:
        port = int(request.GET["port"])
    except KeyError, ValueError:
        port = 0
    state = request.GET.get("state", "")
    if not 1024 <= port <= 65535 or not re.fullmatch(r"[\w-]{16,100}", state):
        return HttpResponseBadRequest("Invalid port or state.")
    # gov has to ask for the access explicitly
    if (access := request.GET.get("access")) not in APIToken.Access.values:
        return HttpResponseBadRequest(
            "Invalid access, use gov login --read or --write."
        )
    name = request.GET.get("name", "")[:50]

    if request.method == "POST":
        _token, secret = APIToken.create_for(
            user=request.user, title=f"gov ({name})" if name else "gov", access=access
        )
        return render(
            request,
            "accounts/cli_login_redirect.html",
            {"action": f"http://127.0.0.1:{port}/", "token": secret, "state": state},
        )

    return render(
        request,
        "accounts/cli_login.html",
        {
            "name": name,
            "days": API_TOKEN_LIFETIME.days,
            "access": APIToken.Access(access),
        },
    )


class SettingsForm(ModelForm):
    """The own name, language and mails, changed together"""

    # Signing in with Google matches it: shown, not changed here
    email = forms.EmailField(
        label=gettext_lazy("Mail address"),
        disabled=True,
        required=False,
        help_text=gettext_lazy("You sign in with it, it can't be changed here."),
    )
    notify_all = forms.TypedChoiceField(
        label=gettext_lazy("Mails"),
        choices=[
            (False, gettext_lazy("About the circles I'm a member of")),
            (True, gettext_lazy("About everything in all circles")),
        ],
        coerce=lambda value: value == "True",
        widget=forms.RadioSelect,
    )

    class Meta:
        model = User
        fields = ["email", "full_name", "short_name", "language", "notify_all"]
        help_texts = {
            "short_name": gettext_lazy(
                "In the menu at the top; without one the start of your mail address."
            ),
            "language": gettext_lazy("Of the pages and the mails."),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["full_name"].required = True
        # No empty choice: without a language the pages follow the browser
        # but the mails are German; saving sets the page's language
        self.fields["language"].choices = settings.LANGUAGES
        self.fields["language"].required = True
        if not self.instance.language:
            self.initial["language"] = get_language()


@login_required  # /accounts/ is exempt from the login middleware
def user_settings(request):
    """Name, short name, language and mails; back to ``?next=`` (the page
    the menu opened it from), else the own page"""
    form = SettingsForm(request.POST or None, instance=request.user)
    if form.is_valid():
        user = form.save()
        # The language of the message and the next page
        activate(user.language)
        messages.success(request, gettext("Your settings have been saved."))
        return redirect(next_url(request) or user)
    return render(
        request,
        "generic/object_form.html",
        {
            "title": gettext("Settings"),
            "form": form,
            "cancel_url": next_url(request) or request.user.get_absolute_url(),
        },
    )
