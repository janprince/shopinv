from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q


class UsernameOrEmailBackend(ModelBackend):
    """Let staff sign in with either their username or their email address.

    Shopkeepers remember one or the other, rarely both. Case-insensitive on both.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()
        identifier = (username or kwargs.get(User.USERNAME_FIELD) or "").strip()
        if not identifier or not password:
            return None
        try:
            user = User.objects.get(
                Q(username__iexact=identifier) | (Q(email__iexact=identifier) & ~Q(email=""))
            )
        except User.DoesNotExist:
            # Run the hasher anyway so timing does not reveal whether an account exists.
            User().set_password(password)
            return None
        except User.MultipleObjectsReturned:
            user = User.objects.filter(username__iexact=identifier).first()
            if user is None:
                return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
