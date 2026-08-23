from django.contrib import admin
from django.templatetags.static import static
from django.urls import include, path
from django.views.generic.base import RedirectView


class FaviconView(RedirectView):
    """Browsers ask for /favicon.ico whatever the <link rel="icon"> tag says.

    The static URL is resolved per request, not at import time: under manifest
    storage there is no manifest until ``collectstatic`` has run, and a
    module-level ``static()`` call would stop the app from starting at all.
    """

    permanent = True

    def get_redirect_url(self, *args, **kwargs):
        return static("img/favicon.svg")


urlpatterns = [
    path("", include(("apps.core.urls", "core"), namespace="core")),
    path("accounts/", include(("apps.accounts.urls", "accounts"), namespace="accounts")),
    path("catalog/", include(("apps.catalog.urls", "catalog"), namespace="catalog")),
    path("stock/", include(("apps.inventory.urls", "inventory"), namespace="inventory")),
    path("sales/", include(("apps.sales.urls", "sales"), namespace="sales")),
    path("reports/", include(("apps.reports.urls", "reports"), namespace="reports")),
    path("manage/", admin.site.urls),
    path("favicon.ico", FaviconView.as_view(), name="favicon"),
]

handler403 = "apps.core.views.error_403"
handler404 = "apps.core.views.error_404"
handler500 = "apps.core.views.error_500"

admin.site.site_header = "JCF Organic — technical administration"
admin.site.site_title = "JCF Organic admin"
admin.site.index_title = "Support tools"
