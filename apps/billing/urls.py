from django.urls import path

from . import views

app_name = "billing"

urlpatterns = [
    path("pricing/", views.pricing, name="pricing"),
    path("billing/", views.account, name="account"),
    path("billing/subscribe/<slug:code>/", views.subscribe, name="subscribe"),
    path("billing/extra-slot/", views.buy_slot, name="buy_slot"),
    path("billing/feature/<int:pk>/", views.feature, name="feature"),
    path("billing/cancel/", views.cancel, name="cancel"),
    path("billing/resume/", views.resume, name="resume"),
    path("billing/success/", views.success, name="success"),
    path("billing/webhook/<slug:provider>/", views.webhook, name="webhook"),
]
