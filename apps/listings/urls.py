from django.urls import path

from . import views

app_name = "listings"

urlpatterns = [
    path("search/", views.search, name="search"),
    path("listings/<int:pk>/<slug:slug>/", views.detail, name="detail"),
]
