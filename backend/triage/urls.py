from django.urls import path

from . import views as v

urlpatterns = [
    path("auth/me", v.me),
    path("auth/login", v.login_view),
    path("auth/local", v.local_login),
    path("auth/logout", v.logout_view),
    path("items", v.items),
    path("items/approve-auto", v.approve_auto),
    path("items/approve-selected", v.approve_selected),
    path("stats", v.stats),
    path("search", v.search),
    path("rules", v.rules),
    path("rules/forget", v.rules_forget),
    path("rules/route", v.rules_route),
    path("items/<int:pk>", v.item_detail),
    path("items/<int:pk>/pdf", v.item_pdf),
    path("items/<int:pk>/<str:action>", v.item_action),
    path("scan", v.scan_view),
    path("scan/status", v.scan_status),
    path("dashboard", v.dashboard),
    path("changelog", v.changelog),
    path("thresholds", v.thresholds),
    path("settings", v.folder_settings),
    path("folders", v.folders),
    path("history", v.history),
    path("history/<int:op_id>/undo", v.undo),
    path("destinations", v.destinations),
    path("vocabulary", v.vocabulary),
]
