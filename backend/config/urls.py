from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.system import views as system_views
from apps.web.diagnostics import email_check

urlpatterns = [
    path("admin/email-check/", email_check),         # superuser-only email diagnostics
    path("admin/", admin.site.urls),
    path("api/", system_views.root),                 # API landing page (JSON)
    path("live", system_views.live),                 # short aliases of /health/live and /health/ready
    path("ready", system_views.ready),
    path("health/", include("apps.system.health_urls")),
    path("api/schema/", SpectacularAPIView.as_view(permission_classes=[], authentication_classes=[]), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema", permission_classes=[], authentication_classes=[])),
    path("api/v1/", include("apps.accounts.urls")),
    path("api/v1/", include("apps.system.urls")),
    path("api/v1/", include("apps.shops.urls")),
    path("api/v1/", include("apps.sync.urls")),
    path("api/v1/", include("apps.subscriptions.urls")),
    path("", include("apps.web.urls")),              # the website: last, so the paths above always win
]
