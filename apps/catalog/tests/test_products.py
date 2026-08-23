from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import Product, Unit
from apps.core.models import AuditAction, AuditEvent
from apps.core.tests.factories import make_category, make_product, make_user
from apps.inventory.models import MovementType, StockMovement


class ProductCreationTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.category = make_category()
        self.client.force_login(self.user)

    def _payload(self, **overrides):
        payload = {
            "name": "Cold-Pressed Coconut Oil 500ml",
            "sku": "coc-500",
            "category": self.category.pk,
            "unit": Unit.BOTTLE,
            "description": "",
            "cost_price": "42.00",
            "selling_price": "65.00",
            "minimum_stock": "6",
            "barcode": "",
            "is_active": "on",
            "opening_quantity": "",
            "opening_expiry": "",
        }
        payload.update(overrides)
        return payload

    def test_a_shopkeeper_can_add_a_product(self):
        response = self.client.post(reverse("catalog:product_create"), self._payload())
        product = Product.objects.get(sku="COC-500")
        self.assertRedirects(response, product.get_absolute_url())
        self.assertEqual(product.selling_price, Decimal("65.00"))
        self.assertEqual(product.stock_quantity, Decimal("0"))

    def test_the_sku_is_stored_uppercase(self):
        self.client.post(reverse("catalog:product_create"), self._payload(sku="  coc-500 "))
        self.assertTrue(Product.objects.filter(sku="COC-500").exists())

    def test_duplicate_sku_is_rejected_with_a_readable_message(self):
        make_product(sku="COC-500")
        response = self.client.post(reverse("catalog:product_create"), self._payload())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already used by another product")
        self.assertEqual(Product.objects.filter(sku="COC-500").count(), 1)

    def test_duplicate_sku_is_also_blocked_at_the_database_level(self):
        make_product(sku="COC-500")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Product.objects.create(
                    name="Another",
                    sku="coc-500",
                    category=self.category,
                    unit=Unit.PIECE,
                    cost_price=Decimal("1"),
                    selling_price=Decimal("2"),
                )

    def test_duplicate_barcode_is_rejected(self):
        make_product(sku="OTHER-1", barcode="6001234567890")
        response = self.client.post(
            reverse("catalog:product_create"), self._payload(barcode="6001234567890")
        )
        self.assertContains(response, "already uses that barcode")

    def test_two_products_may_both_have_no_barcode(self):
        make_product(sku="A-1", barcode="")
        make_product(sku="A-2", barcode="")
        self.assertEqual(Product.objects.filter(barcode="").count(), 2)

    def test_submitted_values_survive_a_validation_failure(self):
        response = self.client.post(
            reverse("catalog:product_create"), self._payload(selling_price="")
        )
        self.assertContains(response, "Cold-Pressed Coconut Oil 500ml")

    def test_creating_a_product_writes_an_audit_event(self):
        self.client.post(reverse("catalog:product_create"), self._payload())
        self.assertTrue(AuditEvent.objects.filter(action=AuditAction.PRODUCT_CREATED).exists())


class OpeningStockTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.category = make_category()
        self.client.force_login(self.user)

    def test_opening_stock_creates_a_movement_not_a_bare_number(self):
        self.client.post(
            reverse("catalog:product_create"),
            {
                "name": "Shea Butter 250g",
                "sku": "SHEA-250",
                "category": self.category.pk,
                "unit": Unit.PIECE,
                "description": "",
                "cost_price": "18.00",
                "selling_price": "32.00",
                "minimum_stock": "10",
                "barcode": "",
                "is_active": "on",
                "opening_quantity": "40",
                "opening_expiry": "",
            },
        )
        product = Product.objects.get(sku="SHEA-250")
        self.assertEqual(product.stock_quantity, Decimal("40"))

        movement = StockMovement.objects.get(product=product)
        self.assertEqual(movement.movement_type, MovementType.OPENING)
        self.assertEqual(movement.quantity, Decimal("40"))
        self.assertEqual(movement.quantity_before, Decimal("0"))
        self.assertEqual(movement.quantity_after, Decimal("40"))
        self.assertEqual(movement.user, self.user)

    def test_opening_stock_is_optional(self):
        self.client.post(
            reverse("catalog:product_create"),
            {
                "name": "Black Soap Bar",
                "sku": "SOAP-BLK",
                "category": self.category.pk,
                "unit": Unit.PIECE,
                "description": "",
                "cost_price": "6.50",
                "selling_price": "12.00",
                "minimum_stock": "20",
                "barcode": "",
                "is_active": "on",
                "opening_quantity": "",
                "opening_expiry": "",
            },
        )
        product = Product.objects.get(sku="SOAP-BLK")
        self.assertEqual(product.stock_quantity, Decimal("0"))
        self.assertFalse(StockMovement.objects.filter(product=product).exists())

    def test_a_whole_unit_product_rejects_a_fractional_opening_quantity(self):
        response = self.client.post(
            reverse("catalog:product_create"),
            {
                "name": "Avocado",
                "sku": "PRD-AVO",
                "category": self.category.pk,
                "unit": Unit.PIECE,
                "description": "",
                "cost_price": "3.00",
                "selling_price": "6.00",
                "minimum_stock": "20",
                "barcode": "",
                "is_active": "on",
                "opening_quantity": "2.5",
                "opening_expiry": "",
            },
        )
        self.assertContains(response, "whole number")
        self.assertFalse(Product.objects.filter(sku="PRD-AVO").exists())

    def test_a_past_expiry_date_on_opening_stock_is_rejected(self):
        yesterday = timezone.localdate() - timezone.timedelta(days=1)
        response = self.client.post(
            reverse("catalog:product_create"),
            {
                "name": "Old Milk",
                "sku": "MLK-OLD",
                "category": self.category.pk,
                "unit": Unit.BOTTLE,
                "description": "",
                "cost_price": "5",
                "selling_price": "9",
                "minimum_stock": "1",
                "barcode": "",
                "is_active": "on",
                "opening_quantity": "3",
                "opening_expiry": yesterday.isoformat(),
            },
        )
        self.assertContains(response, "already passed")


class ProductEditingTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.product = make_product()
        self.client.force_login(self.user)

    def test_the_edit_form_has_no_field_for_stock(self):
        response = self.client.get(reverse("catalog:product_edit", args=[self.product.pk]))
        self.assertNotContains(response, 'name="stock_quantity"')
        self.assertNotContains(response, 'name="opening_quantity"')

    def test_posting_a_stock_quantity_is_ignored(self):
        from apps.core.tests.factories import stock_up

        stock_up(self.product, 10, self.user)
        self.client.post(
            reverse("catalog:product_edit", args=[self.product.pk]),
            {
                "name": self.product.name,
                "sku": self.product.sku,
                "category": self.product.category.pk,
                "unit": self.product.unit,
                "description": "",
                "cost_price": "38.00",
                "selling_price": "62.00",
                "minimum_stock": "6",
                "barcode": "",
                "is_active": "on",
                "stock_quantity": "9999",
            },
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("10"))
        self.assertEqual(self.product.selling_price, Decimal("62.00"))

    def test_editing_records_what_changed(self):
        self.client.post(
            reverse("catalog:product_edit", args=[self.product.pk]),
            {
                "name": self.product.name,
                "sku": self.product.sku,
                "category": self.product.category.pk,
                "unit": self.product.unit,
                "description": "",
                "cost_price": "38.00",
                "selling_price": "62.00",
                "minimum_stock": "6",
                "barcode": "",
                "is_active": "on",
            },
        )
        event = AuditEvent.objects.get(action=AuditAction.PRODUCT_UPDATED)
        self.assertIn("selling_price", event.details["changes"])
        self.assertEqual(event.details["changes"]["selling_price"], ["58.00", "62.00"])


class StockStatusTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def test_status_moves_from_in_stock_to_low_to_out(self):
        from apps.core.tests.factories import stock_up
        from apps.inventory.services import adjust_stock

        product = make_product(minimum="5")
        stock_up(product, 20, self.user)
        product.refresh_from_db()
        self.assertEqual(product.stock_status, "in")

        adjust_stock(
            product=product,
            movement_type=MovementType.CORRECTION_DOWN,
            quantity=Decimal("16"),
            reason="Stock count",
            user=self.user,
        )
        product.refresh_from_db()
        self.assertEqual(product.stock_status, "low")

        adjust_stock(
            product=product,
            movement_type=MovementType.CORRECTION_DOWN,
            quantity=Decimal("4"),
            reason="Stock count",
            user=self.user,
        )
        product.refresh_from_db()
        self.assertEqual(product.stock_status, "out")

    def test_quantities_are_displayed_in_the_products_own_unit(self):
        piece = make_product(sku="P-1", unit=Unit.PIECE)
        kilo = make_product(sku="K-1", unit=Unit.KILOGRAM)
        self.assertEqual(piece.format_quantity(Decimal("3.000")), "3 pc")
        self.assertEqual(kilo.format_quantity(Decimal("1.500")), "1.5 kg")
