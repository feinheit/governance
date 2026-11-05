from django.urls import path

from governance.history import views


urlpatterns = [
    path("history/", views.organization_history, name="history"),
    path("roles/<int:pk>/history/", views.role_history, name="role_history"),
    path("roles/<int:pk>/as-of/", views.role_as_of, name="role_as_of"),
]
