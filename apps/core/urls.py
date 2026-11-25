from django.conf import settings
from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("about/", views.about, name="about"),
    path("contact/", views.contact, name="contact"),
    path("help/", views.help_page, name="help"),
]

if settings.DEBUG:
    urlpatterns.append(path("styleguide/", views.styleguide, name="styleguide"))
