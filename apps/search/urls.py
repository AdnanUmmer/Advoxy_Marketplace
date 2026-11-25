from django.urls import path

from . import views

app_name = "search"

urlpatterns = [
    path("search/", views.results, name="results"),
    path("my/favorites/", views.favorites, name="favorites"),
    path("my/favorites/<int:pk>/toggle/", views.favorite_toggle, name="favorite_toggle"),
    path("my/searches/", views.saved_searches, name="saved"),
    path("my/searches/save/", views.saved_search_create, name="saved_create"),
    path("my/searches/<int:pk>/<str:op>/", views.saved_search_update, name="saved_update"),
]
