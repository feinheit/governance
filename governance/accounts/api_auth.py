from django.utils.translation import activate, gettext as _
from ninja.errors import HttpError
from ninja.security import HttpBearer, SessionAuth

from governance.accounts.middleware import set_user_name
from governance.accounts.models import APIToken


class UserToken(HttpBearer):
    """Personal API tokens: the gov CLI (`gov login`) and scripts"""

    def __init__(self, *, allow_read_only=False):
        super().__init__()
        self.allow_read_only = allow_read_only

    def authenticate(self, request, token):
        if token := APIToken.objects.for_secret(token, extend=False):
            user = token.user
            request.user = user
            request.api_token = token
            # The user middleware only does this for sessions
            if user.language:
                activate(user.language)
            set_user_name(user)
            if (
                token.access == APIToken.Access.READ
                and not self.allow_read_only
                and request.method not in {"GET", "HEAD", "OPTIONS"}
            ):
                raise HttpError(
                    403, _("This API token only allows reading, not changes.")
                )
            # Only uses which are allowed extend the token
            APIToken.objects.extend(token)
            return user
        return None


class UserSession(SessionAuth):
    def __call__(self, request):
        # Invalid tokens are a 401, not the CSRF failure which the session
        # authentication checks first
        if request.headers.get("authorization", "").lower().startswith("bearer "):
            return None
        return super().__call__(request)


def user_auth(*, allow_read_only=False):
    """Tokens first: the session authentication fails without a CSRF token

    Read only tokens are restricted to GET, HEAD and OPTIONS unless
    ``allow_read_only`` is set, e.g. for revoking the token itself."""
    return [UserToken(allow_read_only=allow_read_only), UserSession()]
