from decimal import Decimal

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(_("created"), auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(_("last updated"), auto_now=True)

    class Meta:
        abstract = True


class ShopSettings(models.Model):
    """Single row of shop-wide configuration. Owner editable only."""

    SINGLETON_PK = 1

    shop_name = models.CharField(_("shop name"), max_length=120, default="JCF Organic")
    tagline = models.CharField(
        _("tagline"), max_length=160, blank=True, default="Natural & organic goods"
    )
    phone = models.CharField(_("phone number"), max_length=30, blank=True)
    email = models.EmailField(_("email address"), blank=True)
    address = models.TextField(_("shop address"), blank=True)
    receipt_footer = models.CharField(
        _("receipt footer message"),
        max_length=200,
        blank=True,
        default="Thank you for shopping with us!",
    )
    low_stock_threshold = models.PositiveIntegerField(
        _("default low-stock level"),
        default=5,
        help_text=_("Used for new products that do not set their own level."),
    )
    expiry_warning_days = models.PositiveIntegerField(
        _("expiry warning period (days)"),
        default=30,
        validators=[MinValueValidator(1)],
        help_text=_("Products expiring within this many days are flagged as expiring soon."),
    )
    large_adjustment_threshold = models.DecimalField(
        _("large adjustment size"),
        max_digits=12,
        decimal_places=3,
        default=Decimal("20"),
        help_text=_("Adjustments at or above this quantity ask for extra confirmation."),
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        verbose_name = _("shop settings")
        verbose_name_plural = _("shop settings")

    def __str__(self) -> str:
        return self.shop_name

    def save(self, *args, **kwargs):
        self.pk = self.SINGLETON_PK
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionDenied("Shop settings cannot be deleted.")

    @classmethod
    def load(cls) -> "ShopSettings":
        obj, _created = cls.objects.get_or_create(pk=cls.SINGLETON_PK)
        return obj


class AuditAction(models.TextChoices):
    LOGIN = "login", _("Signed in")
    LOGIN_FAILED = "login_failed", _("Failed sign-in attempt")
    LOGOUT = "logout", _("Signed out")

    PRODUCT_CREATED = "product_created", _("Product created")
    PRODUCT_UPDATED = "product_updated", _("Product updated")
    PRODUCT_STATUS_CHANGED = "product_status_changed", _("Product activated/deactivated")

    CATEGORY_CREATED = "category_created", _("Category created")
    CATEGORY_UPDATED = "category_updated", _("Category updated")
    SUPPLIER_CREATED = "supplier_created", _("Supplier created")
    SUPPLIER_UPDATED = "supplier_updated", _("Supplier updated")

    OPENING_STOCK = "opening_stock", _("Opening stock recorded")
    STOCK_RECEIVED = "stock_received", _("Stock received")
    STOCK_ADJUSTED = "stock_adjusted", _("Stock adjusted")

    SALE_COMPLETED = "sale_completed", _("Sale completed")
    SALE_REVERSED = "sale_reversed", _("Sale reversed")

    USER_CREATED = "user_created", _("User created")
    USER_UPDATED = "user_updated", _("User updated")
    USER_STATUS_CHANGED = "user_status_changed", _("User activated/deactivated")
    PASSWORD_RESET = "password_reset", _("Password reset by owner")

    SETTINGS_UPDATED = "settings_updated", _("Shop settings updated")
    DATA_EXPORTED = "data_exported", _("Data exported")


class AuditEventQuerySet(models.QuerySet):
    def for_object(self, obj):
        return self.filter(object_type=obj._meta.label_lower, object_id=str(obj.pk))


class AuditEvent(models.Model):
    """Append-only record of anything worth asking questions about later.

    Rows can never be edited or deleted through the ORM — the point of an audit
    trail is that it outlives the records it describes.
    """

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_events",
    )
    actor_label = models.CharField(max_length=150, blank=True)
    action = models.CharField(max_length=40, choices=AuditAction.choices, db_index=True)
    object_type = models.CharField(max_length=60, blank=True, db_index=True)
    object_id = models.CharField(max_length=40, blank=True, db_index=True)
    object_label = models.CharField(max_length=200, blank=True)
    summary = models.CharField(max_length=300)
    details = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = AuditEventQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["object_type", "object_id"], name="audit_object_idx"),
            models.Index(fields=["-created_at", "action"], name="audit_recent_idx"),
        ]
        verbose_name = _("audit event")

    def __str__(self) -> str:
        return f"{self.get_action_display()} — {self.summary}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionDenied("Audit events are immutable.")
        if self.actor and not self.actor_label:
            self.actor_label = self.actor.display_name
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionDenied("Audit events cannot be deleted.")
