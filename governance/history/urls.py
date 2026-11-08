from django.urls import path

from governance.history import views


urlpatterns = [
    path("history/", views.history, name="history"),
    path("roles/<int:pk>/as-of/", views.role_as_of, name="role_as_of"),
]
