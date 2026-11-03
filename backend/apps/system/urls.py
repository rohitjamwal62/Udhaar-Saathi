from django.urls import path

from . import views

urlpatterns = [path("app/config", views.AppConfigView.as_view())]
