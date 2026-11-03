from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("health/", include("apps.system.health_urls")),
    path("api/schema/", SpectacularAPIView.as_view(permission_classes=[], authentication_classes=[]), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema", permission_classes=[], authentication_classes=[])),
    path("api/v1/", include("apps.accounts.urls")),
    path("api/v1/", include("apps.system.urls")),
    path("api/v1/", include("apps.shops.urls")),
    path("api/v1/", include("apps.sync.urls")),
    path("api/v1/", include("apps.subscriptions.urls")),
]
