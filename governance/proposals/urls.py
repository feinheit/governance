from django.urls import path, register_converter

from governance.proposals import drafting, views


class KeyConverter:
    """The ID of a role or policy, or the key of one added by a proposal"""

    regex = r"\d+|n\d+"

    def to_python(self, value):
        return value

    def to_url(self, value):
        return str(value)


register_converter(KeyConverter, "key")


urlpatterns = [
    path("proposals/", views.proposal_list, name="proposals"),
    path("proposals/<int:pk>/", views.proposal_detail, name="proposal"),
    path(
        "roles/<int:pk>/proposals/new/",
        drafting.proposal_create,
        name="proposal_create",
    ),
    path(
        "proposals/<int:pk>/tension/",
        drafting.proposal_update,
        name="proposal_update",
    ),
    path(
        "proposals/<int:pk>/publish/",
        views.proposal_publish,
        name="proposal_publish",
    ),
    path(
        "proposals/<int:pk>/draft/",
        views.proposal_back_to_draft,
        name="proposal_back_to_draft",
    ),
    path(
        "proposals/<int:pk>/withdraw/",
        views.proposal_withdraw,
        name="proposal_withdraw",
    ),
    path(
        "proposals/<int:pk>/respond/",
        views.proposal_respond,
        name="proposal_respond",
    ),
    path(
        "proposals/<int:pk>/delete/",
        drafting.proposal_delete,
        name="proposal_delete",
    ),
    path("proposals/<int:pk>/roles/new/", drafting.role_edit, name="proposal_role_add"),
    path(
        "proposals/<int:pk>/roles/<key:key>/",
        drafting.role_edit,
        name="proposal_role",
    ),
    path(
        "proposals/<int:pk>/roles/<key:key>/convert/",
        drafting.role_convert,
        name="proposal_role_convert",
    ),
    path(
        "proposals/<int:pk>/move/",
        drafting.proposal_move,
        name="proposal_move",
    ),
    path(
        "proposals/<int:pk>/policies/new/",
        drafting.policy_edit,
        name="proposal_policy_add",
    ),
    path(
        "proposals/<int:pk>/policies/<key:key>/",
        drafting.policy_edit,
        name="proposal_policy",
    ),
    path(
        "proposals/<int:pk>/roles/<key:key>/remove-circle/",
        drafting.circle_remove,
        name="proposal_circle_remove",
    ),
    path(
        "proposals/<int:pk>/<str:kind>/<key:key>/remove/",
        drafting.subject_remove,
        name="proposal_subject_remove",
    ),
    path(
        "proposals/<int:pk>/<str:kind>/<key:key>/undo/",
        drafting.subject_undo,
        name="proposal_subject_undo",
    ),
]
