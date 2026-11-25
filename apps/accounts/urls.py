from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("signup/", views.signup, name="signup"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("verify/", views.verify_email_sent, name="verify_email_sent"),
    path("verify/resend/", views.verify_email_resend, name="verify_email_resend"),
    path("verify/<str:token>/", views.verify_email_confirm, name="verify_email_confirm"),
    path("password/reset/", views.PasswordResetView.as_view(), name="password_reset"),
    path("password/reset/sent/", views.PasswordResetDoneView.as_view(), name="password_reset_done"),
    path("password/reset/<uidb64>/<token>/", views.PasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("password/reset/complete/", views.PasswordResetCompleteView.as_view(), name="password_reset_complete"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("staff/login/", views.StaffLoginView.as_view(), name="staff_login"),
    path("staff/", views.StaffHomeView.as_view(), name="staff_home"),
]
