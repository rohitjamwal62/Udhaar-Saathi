from django.urls import path

from . import views

urlpatterns = [
    path("auth/signup", views.SignupView.as_view()),
    path("auth/otp/request", views.OtpRequestView.as_view()),
    path("auth/otp/verify", views.OtpVerifyView.as_view()),
    path("auth/login", views.LoginView.as_view()),
    path("auth/token/refresh", views.RefreshView.as_view()),
    path("auth/logout", views.LogoutView.as_view()),
    path("auth/password/forgot", views.ForgotPasswordView.as_view()),
    path("auth/password/reset", views.ResetPasswordView.as_view()),
    path("auth/sessions", views.SessionsView.as_view()),
    path("auth/sessions/<uuid:session_id>", views.SessionsView.as_view()),
    path("me", views.MeView.as_view()),
]
