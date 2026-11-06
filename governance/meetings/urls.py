from django.urls import path

from governance.meetings import elections, processing, views


urlpatterns = [
    path("roles/<int:pk>/meetings/", views.meeting_list, name="meetings"),
    path(
        "roles/<int:pk>/meetings/new/",
        views.meeting_create,
        name="meeting_create",
    ),
    path("meetings/tactical/new/", views.tactical_call, name="tactical_call"),
    path("meetings/<int:pk>/", views.meeting_detail, name="meeting"),
    path("meetings/<int:pk>/step/", views.meeting_step, name="meeting_step"),
    path("agenda/<int:pk>/outcome/", processing.item_outcome, name="item_outcome"),
    path("meetings/<int:pk>/agenda/add/", views.agenda_add, name="agenda_add"),
    path("agenda/<int:pk>/remove/", views.agenda_remove, name="agenda_remove"),
    path("agenda/<int:pk>/move/", views.agenda_move, name="agenda_move"),
    path("meetings/<int:pk>/agenda/order/", views.agenda_order, name="agenda_order"),
    path("agenda/<int:pk>/process/", processing.item_process, name="item_process"),
    path("agenda/<int:pk>/step/", processing.item_step, name="item_step"),
    path("agenda/<int:pk>/complete/", processing.item_complete, name="item_complete"),
    path("agenda/<int:pk>/reopen/", processing.item_reopen, name="item_reopen"),
    path("agenda/<int:pk>/discard/", processing.item_discard, name="item_discard"),
    path(
        "agenda/<int:pk>/proposal/",
        processing.item_to_proposal,
        name="item_to_proposal",
    ),
    path("agenda/<int:pk>/adopt/", processing.item_adopt, name="item_adopt"),
    path(
        "meetings/<int:pk>/elections/",
        elections.election_add,
        name="election_add",
    ),
    path(
        "meetings/<int:pk>/attendees/",
        views.meeting_attendees,
        name="meeting_attendees",
    ),
    path("meetings/<int:pk>/edit/", views.meeting_update, name="meeting_update"),
    path(
        "meetings/<int:pk>/secretary/",
        views.meeting_secretary,
        name="meeting_secretary",
    ),
    path("meetings/<int:pk>/end/", views.meeting_end, name="meeting_end"),
]
