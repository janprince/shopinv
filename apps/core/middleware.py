from django.utils.functional import SimpleLazyObject

from .models import ShopSettings


class TimezoneAndShopMiddleware:
    """Attaches shop settings to the request without querying on every view.

    ``request.shop`` is lazy: templates that never mention the shop name never
    trigger the query.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.shop = SimpleLazyObject(ShopSettings.load)
        response = self.get_response(request)
        return response
