from django.conf.urls.i18n import i18n_patterns
from django.contrib import admin
from django.urls import include, path
from django.views.i18n import set_language
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
    path("i18n/setlang/", set_language, name="set_language"),   # POST: language + next (safe redirect)
    path("", include("apps.web.seo_urls")),          # robots.txt, sitemap.xml, manifest, favicon: one address each
]

# The website. English keeps its addresses (/pricing/); Hindi lives under /hi/ (/hi/pricing/), so each language has its own
# addresses that search engines can index. Last, so the paths above always win.
urlpatterns += i18n_patterns(path("", include("apps.web.urls")), prefix_default_language=False)
