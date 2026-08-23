from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.test import Client, TestCase
from django.urls import reverse

from apps.core.audit import changed_fields, record
from apps.core.models import AuditAction, AuditEvent, ShopSettings
from apps.core.tests.factories import make_owner, make_product, make_user, stock_up
from apps.inventory.models import MovementType
from apps.inventory.services import adjust_stock
from apps.sales.services import complete_sale


class AuditEventTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def test_an_audit_event_can_never_be_edited(self):
        event = record(AuditAction.LOGIN, actor=self.user, summary="Signed in")
        event.summary = "Something else"
        with self.assertRaises(PermissionDenied):
            event.save()

    def test_an_audit_event_can_never_be_deleted(self):
        event = record(AuditAction.LOGIN, actor=self.user, summary="Signed in")
        with self.assertRaises(PermissionDenied):
            event.delete()

    def test_the_actors_name_survives_the_account_being_removed(self):
        event = record(AuditAction.LOGIN, actor=self.user, summary="Signed in")
        self.assertEqual(event.actor_label, self.user.display_name)

        self.user.delete()
        event.refresh_from_db()
        self.assertIsNone(event.actor)
        self.assertEqual(event.actor_label, "Kofi")

    def test_changed_fields_reports_only_real_differences(self):
        diff = changed_fields(
            {"price": Decimal("10.00"), "name": "Same"},
            {"price": Decimal("12.00"), "name": "Same"},
        )
        self.assertEqual(diff, {"price": ["10.00", "12.00"]})

    def test_an_event_points_back_at_the_record_it_describes(self):
        product = make_product()
        event = record(AuditAction.PRODUCT_CREATED, actor=self.user, obj=product, summary="Made it")
        self.assertEqual(event.object_type, "catalog.product")
        self.assertEqual(event.object_id, str(product.pk))
        self.assertIn(product.sku, event.object_label)


class SensitiveActionsAreAuditedTests(TestCase):
    """Anything that moves money, stock or access must leave a trace."""

    def setUp(self):
        self.owner = make_owner()
        self.keeper = make_user()
        self.product = make_product()

    def test_stock_receiving_sale_and_adjustment_all_leave_a_trace(self):
        stock_up(self.product, 20, self.keeper)
        complete_sale(
            raw_lines=[{"product_id": self.product.pk, "quantity": "2"}], user=self.keeper
        )
        adjust_stock(
            product=self.product,
            movement_type=MovementType.DAMAGED,
            quantity=Decimal("1"),
            reason="Broken",
            user=self.keeper,
        )

        recorded = set(AuditEvent.objects.values_list("action", flat=True))
        for action in (
            AuditAction.STOCK_RECEIVED,
            AuditAction.SALE_COMPLETED,
            AuditAction.STOCK_ADJUSTED,
        ):
            self.assertIn(action, recorded)

    def test_changing_shop_settings_records_what_changed(self):
        self.client.force_login(self.owner)
        self.client.post(
            reverse("core:settings"),
            {
                "shop_name": "JCF Organic Market",
                "tagline": "Natural goods",
                "phone": "",
                "email": "",
                "address": "",
                "receipt_footer": "Thanks",
                "low_stock_threshold": "5",
                "expiry_warning_days": "45",
                "large_adjustment_threshold": "20",
            },
        )
        event = AuditEvent.objects.get(action=AuditAction.SETTINGS_UPDATED)
        self.assertIn("shop_name", event.details["changes"])
        self.assertIn("expiry_warning_days", event.details["changes"])

        ShopSettings.load().refresh_from_db()
        self.assertEqual(ShopSettings.load().expiry_warning_days, 45)


class AuditViewTests(TestCase):
    def setUp(self):
        self.owner = make_owner()
        self.keeper = make_user()
        self.product = make_product()
        stock_up(self.product, 5, self.keeper)

    def test_only_the_owner_can_read_the_audit_history(self):
        self.client.force_login(self.keeper)
        self.assertEqual(self.client.get(reverse("core:audit_log")).status_code, 403)

        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("core:audit_log")).status_code, 200)

    def test_the_audit_history_can_be_filtered_by_action(self):
        self.client.force_login(self.owner)
        response = self.client.get(
            reverse("core:audit_log"), {"action": AuditAction.STOCK_RECEIVED, "period": "today"}
        )
        self.assertContains(response, "Received")

    def test_there_is_no_url_that_deletes_an_audit_event(self):
        self.client.force_login(self.owner)
        event = AuditEvent.objects.first()
        self.assertEqual(self.client.post(f"/audit/{event.pk}/delete/").status_code, 404)


class ShopSettingsTests(TestCase):
    def test_settings_are_a_single_row_no_matter_how_often_they_are_saved(self):
        first = ShopSettings.load()
        first.shop_name = "One"
        first.save()

        second = ShopSettings.load()
        second.shop_name = "Two"
        second.save()

        self.assertEqual(ShopSettings.objects.count(), 1)
        self.assertEqual(ShopSettings.load().shop_name, "Two")

    def test_settings_cannot_be_deleted(self):
        with self.assertRaises(PermissionDenied):
            ShopSettings.load().delete()

    def test_the_expiry_warning_window_actually_drives_the_warnings(self):
        from datetime import timedelta

        from django.utils import timezone

        owner = make_owner()
        product = make_product()
        stock_up(product, 5, owner, expiry=timezone.localdate() + timedelta(days=40))

        settings_obj = ShopSettings.load()
        settings_obj.expiry_warning_days = 30
        settings_obj.save()
        self.assertIsNone(product.expiry_state(settings_obj.expiry_warning_days))

        settings_obj.expiry_warning_days = 60
        settings_obj.save()
        self.assertEqual(product.expiry_state(settings_obj.expiry_warning_days), "expiring")


class HealthCheckTests(TestCase):
    def test_the_health_endpoint_answers_without_a_login(self):
        response = self.client.get(reverse("core:healthz"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_the_health_endpoint_bypasses_https_redirects(self):
        with self.settings(
            SECURE_SSL_REDIRECT=True,
            SECURE_REDIRECT_EXEMPT=[r"^healthz/$"],
        ):
            client = Client()
            health_response = client.get(reverse("core:healthz"))
            normal_response = client.get(reverse("core:dashboard"))

        self.assertEqual(health_response.status_code, 200)
        self.assertEqual(normal_response.status_code, 301)
