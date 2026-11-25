from django.urls import path

from . import views

app_name = "listings"

urlpatterns = [
    path("listings/<int:pk>/<slug:slug>/", views.detail, name="detail"),
    # Owner management
    path("my/listings/", views.mine, name="mine"),
    path("my/listings/new/", views.create, name="create"),
    path("my/listings/<int:pk>/edit/", views.edit, name="edit"),
    path("my/listings/<int:pk>/<str:action>/", views.transition, name="transition"),
    path("my/listings/<int:pk>/photos/upload/", views.photo_upload, name="photo_upload"),
    path("my/listings/<int:pk>/photos/reorder/", views.photo_reorder, name="photo_reorder"),
    path("my/listings/<int:pk>/photos/<int:photo_id>/<str:op>/", views.photo_action, name="photo_action"),
]
