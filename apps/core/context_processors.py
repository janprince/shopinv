from django.conf import settings


def shop_context(request):
    return {
        "DEBUG": settings.DEBUG,
        "shop": getattr(request, "shop", None),
        "CURRENCY_SYMBOL": settings.CURRENCY_SYMBOL,
        "is_owner": bool(
            getattr(request, "user", None)
            and request.user.is_authenticated
            and request.user.is_owner
        ),
    }
