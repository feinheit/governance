from django.urls import path

from governance.accounts import views


urlpatterns = [
    path("login/", views.login, name="login"),
    path("oauth2/", views.oauth2, name="accounts_oauth2"),
    path("logout/", views.logout, name="logout"),
    path("api-tokens/", views.api_tokens, name="api_tokens"),
    path(
        "api-tokens/<int:pk>/delete/",
        views.api_token_delete,
        name="api_token_delete",
    ),
    path("notifications/", views.notifications, name="notifications"),
    path("language/", views.language, name="language"),
]
