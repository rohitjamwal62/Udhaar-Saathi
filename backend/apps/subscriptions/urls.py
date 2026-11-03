from django.urls import path

from . import views

urlpatterns = [
    path("subscriptions/current", views.CurrentView.as_view()),
    path("subscriptions/payments", views.PaymentsView.as_view()),
    path("subscriptions/orders", views.OrdersView.as_view()),
    path("subscriptions/verify", views.VerifyView.as_view()),
    path("subscriptions/cancel", views.CancelView.as_view()),
    path("webhooks/razorpay", views.RazorpayWebhookView.as_view()),
]
