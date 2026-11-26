from django.urls import path

from . import views

app_name = "agencies"

urlpatterns = [
    path("agents/", views.agents, name="agents"),
    path("agents/<int:pk>/", views.agent_detail, name="agent"),
    path("agencies/", views.agencies, name="agencies"),
    path("agencies/<slug:slug>/", views.agency_detail, name="agency"),
    path("my/team/", views.team, name="team"),
    path("my/team/invite/", views.team_invite, name="team_invite"),
    path("my/team/invitations/<int:pk>/revoke/", views.team_revoke, name="team_revoke"),
    path("my/team/members/<int:pk>/remove/", views.team_remove, name="team_remove"),
    path("my/team/leave/", views.team_leave, name="team_leave"),
    path("invitations/<str:token>/", views.invitation, name="invitation"),
]
