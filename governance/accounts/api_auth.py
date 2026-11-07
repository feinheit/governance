from django.utils.translation import activate, gettext as _
from ninja.errors import HttpError
from ninja.security import HttpBearer, SessionAuth

from governance.accounts.middleware import set_user_name
from governance.accounts.models import APIToken


class UserToken(HttpBearer):
    """Personal API tokens: the gov CLI (`gov login`) and scripts"""

    def authenticate(self, request, token):
        if token := APIToken.objects.for_secret(token, extend=False):
            user = token.user
            request.user = user
            request.api_token = token
            # The user middleware only does this for sessions
            if user.language:
                activate(user.language)
            set_user_name(user)
            if token.access == APIToken.Access.READ and request.method not in {
                "GET",
                "HEAD",
                "OPTIONS",
            }:
                raise HttpError(
                    403, _("This API token only allows reading, not changes.")
                )
            # Only uses which are allowed extend the token
            APIToken.objects.extend(token)
            return user
        return None


def user_auth():
    """Tokens first: the session authentication fails without a CSRF token"""
    return [UserToken(), SessionAuth()]
