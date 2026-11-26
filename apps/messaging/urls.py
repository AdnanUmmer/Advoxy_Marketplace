from django.urls import path

from . import views

app_name = "messaging"

urlpatterns = [
    path("inquire/<int:pk>/", views.inquire, name="inquire"),
    path("messages/", views.inbox, name="inbox"),
    path("messages/list/", views.thread_list, name="thread_list"),
    path("messages/unread/", views.unread_badge, name="unread_badge"),
    path("messages/<int:pk>/", views.thread, name="thread"),
    path("messages/<int:pk>/send/", views.send, name="send"),
    path("messages/<int:pk>/poll/", views.poll, name="poll"),
]
