from django.urls import path

from . import views

app_name = "staff"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("moderation/", views.moderation, name="moderation"),
    path("moderation/approve-selected/", views.moderation_bulk_approve, name="moderation_bulk"),
    path("moderation/<int:pk>/", views.moderation_action, name="moderation_action"),
    path("listings/", views.listings, name="listings"),
    path("listings/bulk/", views.listings_bulk, name="listings_bulk"),
    path("users/", views.users, name="users"),
    path("users/<int:pk>/", views.user_detail, name="user_detail"),
    path("users/<int:pk>/<str:action>/", views.user_action, name="user_action"),
    path("verifications/", views.verifications, name="verifications"),
    path("verifications/<int:pk>/review/", views.verification_review, name="verification_review"),
    path("verifications/<int:pk>/file/", views.verification_file, name="verification_file"),
]
