from django.urls import path

from governance.roles import (
    addresses,
    assignments,
    browser,
    domain_policies,
    editing,
    settings_views,
    views,
)
from governance.roles.export import export_markdown


urlpatterns = [
    path("", views.start, name="start"),
    path("organization/", views.organization, name="organization"),
    path("roles/<int:pk>/", views.role_detail, name="role"),
    path("roles/<int:pk>/context/", views.role_context, name="role_context"),
    path("roles/<int:pk>/members/", views.circle_members, name="circle_members"),
    path(
        "roles/<int:pk>/assignments/",
        assignments.assignments,
        name="role_assignments",
    ),
    path(
        "assignments/<int:pk>/",
        assignments.assignment_update,
        name="assignment_update",
    ),
    path(
        "assignments/<int:pk>/end/",
        assignments.assignment_end,
        name="assignment_end",
    ),
    path(
        "roles/<int:pk>/settings/",
        settings_views.role_settings,
        name="role_settings",
    ),
    path("roles/<int:pk>/strategy/", editing.strategy, name="role_strategy"),
    # Accountabilities and domains
    path("roles/<int:pk>/<str:kind>/order/", editing.texts_order, name="texts_order"),
    path(
        "roles/<int:pk>/<str:kind>/<str:key>/move/",
        editing.text_move,
        name="text_move",
    ),
    # Explicit kinds: roles/<pk>/proposals/new/ and others exist too
    *[
        path(
            f"roles/<int:role_pk>/{kind}/new/",
            editing.item_edit,
            {"kind": kind},
            name=f"role_{kind}_add",
        )
        for kind in editing.MODELS
    ],
    path("items/<str:kind>/<int:pk>/", editing.item_edit, name="role_item"),
    path(
        "items/<str:kind>/<int:pk>/delete/",
        editing.item_delete,
        name="role_item_delete",
    ),
    path("policies/<int:pk>/", views.policy_detail, name="policy"),
    path(
        "roles/<int:pk>/domain-policies/new/",
        domain_policies.domain_policy_edit,
        name="domain_policy_add",
    ),
    path(
        "roles/<int:pk>/domain-policies/<int:policy_pk>/",
        domain_policies.domain_policy_edit,
        name="domain_policy",
    ),
    path(
        "roles/<int:pk>/domain-policies/<int:policy_pk>/remove/",
        domain_policies.domain_policy_remove,
        name="domain_policy_remove",
    ),
    path("circles/", browser.circle_browser, name="circle_browser"),
    path("people/", views.people, name="people"),
    path("people/addresses/", addresses.mail_addresses, name="mail_addresses"),
    path("people/<int:pk>/", views.person_detail, name="person"),
    path("export/governance.md", export_markdown, name="export_markdown"),
]
