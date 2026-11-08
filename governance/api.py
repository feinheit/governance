from typing import Literal

from django.conf import settings
from django.contrib.auth.decorators import login_required
from ninja import NinjaAPI, Schema

from governance.accounts.api import router as accounts_router
from governance.accounts.api_auth import user_auth
from governance.backup import backup
from governance.help import PAGES
from governance.proposals.api import router as proposals_router
from governance.roles.api import router as roles_router


api = NinjaAPI(
    title="Governance",
    auth=user_auth(),
    docs_decorator=login_required,
    urls_namespace="api",
)
api.add_router("/", accounts_router)
api.add_router("/", roles_router)
api.add_router("/", proposals_router)


@api.get("backup/")
def backup_data(request, *, people: bool = False):
    """The JSON backup, what the token's user sees, the people only when
    asked for (``gov backup``, ``scripts/fetch_backup.py``)"""
    return backup(request.user, with_people=people)


class ConstitutionOut(Schema):
    language: str
    markdown: str


@api.get("constitution/", response=ConstitutionOut)
def constitution(request, *, language: Literal["en", "de"] = "en"):
    """The Holacracy Constitution 5.0 the app follows, as Markdown, like
    /help/constitution/"""
    path = settings.BASE_DIR / "docs" / PAGES[language]["constitution"]
    return {"language": language, "markdown": path.read_text()}
