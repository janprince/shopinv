"""Server-side role enforcement.

Hiding a nav link is a courtesy; these mixins are the actual rule. Every
owner-only view must use one of them.
"""

from functools import wraps

from django.contrib.auth.mixins import AccessMixin, LoginRequiredMixin
from django.core.exceptions import PermissionDenied


class StaffRequiredMixin(LoginRequiredMixin):
    """Any signed-in, active member of shop staff."""


class OwnerRequiredMixin(LoginRequiredMixin, AccessMixin):
    """Owner only. Signed-in shopkeepers get 403, anonymous users get the login page."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.is_owner:
            raise PermissionDenied("This area is available to the shop owner only.")
        return super().dispatch(request, *args, **kwargs)


def owner_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login

            return redirect_to_login(request.get_full_path())
        if not request.user.is_owner:
            raise PermissionDenied("This area is available to the shop owner only.")
        return view_func(request, *args, **kwargs)

    return _wrapped
