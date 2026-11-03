from django.urls import path

from . import views

urlpatterns = [
    path("shops", views.ShopsView.as_view()),
    path("shops/<uuid:shop_id>", views.ShopDetailView.as_view()),
    path("shops/<uuid:shop_id>/customers", views.CustomersView.as_view()),
    path("shops/<uuid:shop_id>/customers/<uuid:customer_id>/ledger", views.LedgerView.as_view()),
    path("shops/<uuid:shop_id>/dashboard", views.DashboardView.as_view()),
    path("shops/<uuid:shop_id>/reports/receivables", views.ReceivablesReportView.as_view()),
]
