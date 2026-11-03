from django.urls import path

from . import views

urlpatterns = [path("sync/batch", views.SyncBatchView.as_view())]
