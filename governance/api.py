from django.contrib.auth.decorators import login_required
from ninja import NinjaAPI

from governance.accounts.api import router as accounts_router
from governance.accounts.api_auth import user_auth
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
