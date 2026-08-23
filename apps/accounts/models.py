from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.db import models
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _


class Role(models.TextChoices):
    """Two roles only. Keeping this small is what keeps permissions understandable."""

    OWNER = "owner", _("Owner")
    SHOPKEEPER = "shopkeeper", _("Shopkeeper")


class UserQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def owners(self):
        return self.filter(role=Role.OWNER)


class UserManager(DjangoUserManager.from_queryset(UserQuerySet)):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("role", Role.OWNER)
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    """Shop staff account.

    Django's own auth handles password hashing, sessions and login throttling hooks.
    We only add the shop role and a phone number.
    """

    email = models.EmailField(_("email address"), blank=True)
    role = models.CharField(
        _("role"),
        max_length=20,
        choices=Role.choices,
        default=Role.SHOPKEEPER,
        help_text=_("Owners can manage users, settings and reversals. Shopkeepers run the shop."),
    )
    phone = models.CharField(_("phone number"), max_length=20, blank=True)

    objects = UserManager()

    class Meta:
        ordering = ["first_name", "last_name", "username"]
        constraints = [
            models.UniqueConstraint(
                Lower("email"),
                condition=~models.Q(email=""),
                name="user_email_unique_ci",
            )
        ]

    def __str__(self) -> str:
        return self.display_name

    @property
    def display_name(self) -> str:
        full = self.get_full_name().strip()
        return full or self.username

    @property
    def initials(self) -> str:
        parts = [p for p in (self.first_name, self.last_name) if p]
        if parts:
            return "".join(p[0] for p in parts[:2]).upper()
        return self.username[:2].upper()

    @property
    def is_owner(self) -> bool:
        return self.role == Role.OWNER

    @property
    def is_shopkeeper(self) -> bool:
        return self.role == Role.SHOPKEEPER

    def save(self, *args, **kwargs):
        self.email = (self.email or "").strip().lower()
        # A Django superuser is always treated as an owner so support access is never
        # accidentally downgraded.
        if self.is_superuser:
            self.role = Role.OWNER
        return super().save(*args, **kwargs)
