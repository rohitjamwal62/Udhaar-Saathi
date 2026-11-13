from django.urls import path

from . import views

urlpatterns = [path("live", views.live), path("ready", views.ready), path("mail", views.mail_health)]
