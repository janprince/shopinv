from datetime import timedelta
from decimal import Decimal
from itertools import pairwise

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import Unit
from apps.core.models import AuditAction, AuditEvent
from apps.core.tests.factories import (
    make_product,
    make_supplier,
    make_user,
    stock_up,
)
from apps.inventory.models import MovementType, StockBatch, StockMovement
from apps.inventory.services import (
    InsufficientStock,
    StockError,
    adjust_stock,
    receive_stock,
    remove_stock,
)


class ReceiveStockTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.product = make_product()
        self.supplier = make_supplier()

    def test_receiving_creates_a_batch_and_a_movement_together(self):
        batch = receive_stock(
            product=self.product,
            quantity=Decimal("24"),
            unit_cost=Decimal("36.50"),
            user=self.user,
            supplier=self.supplier,
            batch_number="LOT-2026-08",
        )
        self.product.refresh_from_db()

        self.assertEqual(self.product.stock_quantity, Decimal("24"))
        self.assertEqual(batch.quantity_remaining, Decimal("24"))
        self.assertEqual(batch.supplier, self.supplier)
        self.assertEqual(batch.received_by, self.user)

        movement = StockMovement.objects.get(product=self.product)
        self.assertEqual(movement.movement_type, MovementType.RECEIVED)
        self.assertEqual(movement.quantity, Decimal("24"))
        self.assertEqual(movement.quantity_before, Decimal("0"))
        self.assertEqual(movement.quantity_after, Decimal("24"))
        self.assertEqual(movement.batch, batch)
        self.assertEqual(movement.unit_cost, Decimal("36.50"))

    def test_receiving_updates_the_products_default_cost(self):
        receive_stock(
            product=self.product,
            quantity=Decimal("10"),
            unit_cost=Decimal("41.00"),
            user=self.user,
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.cost_price, Decimal("41.00"))

    def test_the_default_cost_can_be_left_alone(self):
        receive_stock(
            product=self.product,
            quantity=Decimal("10"),
            unit_cost=Decimal("41.00"),
            user=self.user,
            update_cost_price=False,
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.cost_price, Decimal("38.00"))

    def test_stock_accumulates_across_deliveries(self):
        stock_up(self.product, 10, self.user)
        stock_up(self.product, 15, self.user)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("25"))
        self.assertEqual(StockBatch.objects.filter(product=self.product).count(), 2)

    def test_zero_or_negative_quantities_are_refused(self):
        for bad in ("0", "-5"):
            with self.subTest(quantity=bad):
                with self.assertRaises(StockError):
                    receive_stock(
                        product=self.product,
                        quantity=Decimal(bad),
                        unit_cost=Decimal("10"),
                        user=self.user,
                    )

    def test_whole_unit_products_refuse_fractional_deliveries(self):
        pieces = make_product(sku="P-1", unit=Unit.PIECE)
        with self.assertRaises(StockError):
            receive_stock(
                product=pieces, quantity=Decimal("2.5"), unit_cost=Decimal("1"), user=self.user
            )

    def test_weighed_products_accept_fractional_deliveries(self):
        rice = make_product(sku="RICE-1", unit=Unit.KILOGRAM)
        receive_stock(
            product=rice, quantity=Decimal("12.5"), unit_cost=Decimal("14"), user=self.user
        )
        rice.refresh_from_db()
        self.assertEqual(rice.stock_quantity, Decimal("12.500"))

    def test_receiving_is_audited(self):
        stock_up(self.product, 10, self.user)
        self.assertTrue(AuditEvent.objects.filter(action=AuditAction.STOCK_RECEIVED).exists())

    def test_the_whole_receipt_view_is_a_single_atomic_step(self):
        """A rejected confirmation must leave nothing behind."""
        self.client.force_login(self.user)
        before = StockBatch.objects.count()
        self.client.post(
            reverse("inventory:receive"),
            {"product": self.product.pk, "quantity": "0", "unit_cost": "10", "stage": "confirm"},
        )
        self.assertEqual(StockBatch.objects.count(), before)


class ExpiryAndFefoTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.product = make_product()
        self.today = timezone.localdate()

    def test_stock_leaves_by_earliest_expiry_first(self):
        later = stock_up(
            self.product, 10, self.user, expiry=self.today + timedelta(days=90), batch_number="LATE"
        )
        sooner = stock_up(
            self.product, 10, self.user, expiry=self.today + timedelta(days=10), batch_number="SOON"
        )

        with transaction.atomic():
            product = self.product.__class__.objects.select_for_update().get(pk=self.product.pk)
            consumptions = remove_stock(
                product=product,
                quantity=Decimal("12"),
                movement_type=MovementType.DAMAGED,
                user=self.user,
                reason="Flood",
            )

        sooner.refresh_from_db()
        later.refresh_from_db()
        self.assertEqual(sooner.quantity_remaining, Decimal("0"))
        self.assertEqual(later.quantity_remaining, Decimal("8"))
        self.assertEqual(consumptions[0].batch.pk, sooner.pk)

    def test_batches_without_an_expiry_are_used_after_dated_ones(self):
        undated = stock_up(self.product, 5, self.user, batch_number="NONE")
        dated = stock_up(
            self.product,
            5,
            self.user,
            expiry=self.today + timedelta(days=200),
            batch_number="DATED",
        )

        with transaction.atomic():
            product = self.product.__class__.objects.select_for_update().get(pk=self.product.pk)
            remove_stock(
                product=product,
                quantity=Decimal("5"),
                movement_type=MovementType.MISSING,
                user=self.user,
                reason="Count",
            )

        dated.refresh_from_db()
        undated.refresh_from_db()
        self.assertEqual(dated.quantity_remaining, Decimal("0"))
        self.assertEqual(undated.quantity_remaining, Decimal("5"))

    def test_products_that_never_expire_work_normally(self):
        stock_up(self.product, 10, self.user)
        self.product.refresh_from_db()
        self.assertIsNone(self.product.earliest_expiry())
        self.assertIsNone(self.product.expiry_state(30))

    def test_expiry_state_reflects_the_soonest_live_batch(self):
        stock_up(self.product, 5, self.user, expiry=self.today + timedelta(days=5))
        self.assertEqual(self.product.expiry_state(30), "expiring")

        past = make_product(sku="PAST-1")
        batch = stock_up(past, 5, self.user, expiry=self.today + timedelta(days=1))
        StockBatch.objects.filter(pk=batch.pk).update(expiry_date=self.today - timedelta(days=1))
        self.assertEqual(past.expiry_state(30), "expired")


class AdjustmentTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.product = make_product()
        stock_up(self.product, 20, self.user)
        self.product.refresh_from_db()

    def _adjust(self, movement_type, quantity, reason="Because"):
        return adjust_stock(
            product=self.product,
            movement_type=movement_type,
            quantity=Decimal(str(quantity)),
            reason=reason,
            user=self.user,
        )

    def test_damaged_stock_reduces_the_count(self):
        self._adjust(MovementType.DAMAGED, 3, "Bottles broke in transit")
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("17"))

        movement = StockMovement.objects.filter(movement_type=MovementType.DAMAGED).get()
        self.assertEqual(movement.quantity, Decimal("-3"))
        self.assertEqual(movement.quantity_before, Decimal("20"))
        self.assertEqual(movement.quantity_after, Decimal("17"))
        self.assertEqual(movement.reason, "Bottles broke in transit")

    def test_expired_missing_and_downward_corrections_all_reduce_stock(self):
        for movement_type in (
            MovementType.EXPIRED,
            MovementType.MISSING,
            MovementType.CORRECTION_DOWN,
        ):
            with self.subTest(type=movement_type):
                before = self.product.stock_quantity
                self._adjust(movement_type, 2)
                self.product.refresh_from_db()
                self.assertEqual(self.product.stock_quantity, before - 2)

    def test_a_customer_return_puts_stock_back(self):
        self._adjust(MovementType.RETURN, 2, "Customer changed their mind")
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("22"))

        movement = StockMovement.objects.filter(movement_type=MovementType.RETURN).get()
        self.assertEqual(movement.quantity, Decimal("2"))
        self.assertTrue(movement.is_increase)
        self.assertEqual(movement.direction_label, "Added")

    def test_an_upward_correction_adds_stock(self):
        self._adjust(MovementType.CORRECTION_UP, 5, "Found a box in the back")
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("25"))

    def test_stock_can_never_go_below_zero(self):
        with self.assertRaises(InsufficientStock):
            self._adjust(MovementType.DAMAGED, 25)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("20"))

    def test_nothing_is_written_when_an_adjustment_is_refused(self):
        before = StockMovement.objects.count()
        with self.assertRaises(InsufficientStock):
            self._adjust(MovementType.MISSING, 999)
        self.assertEqual(StockMovement.objects.count(), before)

    def test_a_reason_is_always_required(self):
        with self.assertRaises(StockError):
            self._adjust(MovementType.DAMAGED, 1, reason="   ")

    def test_a_sale_cannot_be_faked_as_an_adjustment(self):
        with self.assertRaises(StockError):
            self._adjust(MovementType.SALE, 1)

    def test_adjustments_are_audited_with_before_and_after(self):
        self._adjust(MovementType.DAMAGED, 3, "Broken")
        event = AuditEvent.objects.get(action=AuditAction.STOCK_ADJUSTED)
        self.assertEqual(event.details["stock_before"], "20.000")
        self.assertEqual(event.details["stock_after"], "17.000")
        self.assertEqual(event.details["reason"], "Broken")

    def test_an_adjustment_can_target_one_specific_batch(self):
        second = stock_up(self.product, 10, self.user, batch_number="SECOND")
        adjust_stock(
            product=self.product,
            movement_type=MovementType.DAMAGED,
            quantity=Decimal("4"),
            reason="Crushed carton",
            user=self.user,
            batch=second,
        )
        second.refresh_from_db()
        self.assertEqual(second.quantity_remaining, Decimal("6"))

    def test_an_adjustment_cannot_take_more_than_a_chosen_batch_holds(self):
        second = stock_up(self.product, 3, self.user, batch_number="SMALL")
        with self.assertRaises(InsufficientStock):
            adjust_stock(
                product=self.product,
                movement_type=MovementType.DAMAGED,
                quantity=Decimal("5"),
                reason="Crushed",
                user=self.user,
                batch=second,
            )


class LedgerIntegrityTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.product = make_product()
        stock_up(self.product, 10, self.user)

    def test_a_movement_can_never_be_edited(self):
        movement = StockMovement.objects.first()
        movement.quantity = Decimal("999")
        with self.assertRaises(PermissionDenied):
            movement.save()

    def test_a_movement_can_never_be_deleted(self):
        movement = StockMovement.objects.first()
        with self.assertRaises(PermissionDenied):
            movement.delete()

    def test_the_database_refuses_a_negative_stock_figure(self):
        from apps.catalog.models import Product

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Product.objects.filter(pk=self.product.pk).update(stock_quantity=Decimal("-1"))

    def test_the_database_refuses_a_negative_batch_remainder(self):
        batch = StockBatch.objects.first()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                StockBatch.objects.filter(pk=batch.pk).update(quantity_remaining=Decimal("-1"))

    def test_the_ledger_always_sums_to_the_stock_on_hand(self):
        adjust_stock(
            product=self.product,
            movement_type=MovementType.DAMAGED,
            quantity=Decimal("2"),
            reason="Broken",
            user=self.user,
        )
        adjust_stock(
            product=self.product,
            movement_type=MovementType.RETURN,
            quantity=Decimal("1"),
            reason="Returned",
            user=self.user,
        )
        self.product.refresh_from_db()

        from django.db.models import Sum

        ledger = StockMovement.objects.filter(product=self.product).aggregate(
            total=Sum("quantity")
        )["total"]
        batches = StockBatch.objects.filter(product=self.product).aggregate(
            total=Sum("quantity_remaining")
        )["total"]
        self.assertEqual(ledger, self.product.stock_quantity)
        self.assertEqual(batches, self.product.stock_quantity)

    def test_before_and_after_figures_chain_together(self):
        adjust_stock(
            product=self.product,
            movement_type=MovementType.DAMAGED,
            quantity=Decimal("2"),
            reason="Broken",
            user=self.user,
        )
        movements = list(StockMovement.objects.filter(product=self.product).order_by("id"))
        for earlier, later in pairwise(movements):
            self.assertEqual(earlier.quantity_after, later.quantity_before)


class AdjustmentViewTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.product = make_product()
        stock_up(self.product, 20, self.user)
        self.client.force_login(self.user)

    def _post(self, **overrides):
        payload = {
            "product": self.product.pk,
            "movement_type": MovementType.DAMAGED,
            "quantity": "3",
            "batch": "",
            "reason": "Bottles broke in transit",
            "notes": "",
        }
        payload.update(overrides)
        return self.client.post(reverse("inventory:adjust"), payload)

    def test_the_first_post_shows_a_review_and_saves_nothing(self):
        response = self._post()
        self.assertContains(response, "About to record")
        self.assertContains(response, "Confirm")
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("20"))

    def test_the_review_shows_the_expected_quantity_afterwards(self):
        response = self._post()
        self.assertContains(response, "17")

    def test_confirming_applies_the_change(self):
        self._post(stage="confirm")
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("17"))

    def test_going_back_returns_to_the_form_with_the_values_kept(self):
        response = self._post(stage="edit")
        self.assertContains(response, "Bottles broke in transit")
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("20"))

    def test_taking_more_than_there_is_fails_validation(self):
        response = self._post(quantity="50")
        self.assertContains(response, "Stock can never go below zero")
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("20"))

    def test_a_large_adjustment_gets_a_louder_warning(self):
        response = self._post(quantity="20")
        self.assertContains(response, "large change")


class FilterPersistenceTests(TestCase):
    """Changing the date range must not silently discard the other filters."""

    def setUp(self):
        self.user = make_user()
        self.product = make_product()
        stock_up(self.product, 10, self.user)
        self.client.force_login(self.user)

    def test_period_shortcuts_keep_the_product_filter(self):
        response = self.client.get(
            reverse("inventory:movements"), {"product": self.product.pk, "period": "week"}
        )
        self.assertEqual(response.status_code, 200)
        # Every shortcut link should still carry the product it was filtered by.
        self.assertContains(response, f"product={self.product.pk}")

    def test_applying_a_date_range_keeps_the_product_filter(self):
        response = self.client.get(
            reverse("inventory:movements"), {"product": self.product.pk, "period": "month"}
        )
        self.assertContains(
            response, f'<input type="hidden" name="product" value="{self.product.pk}">', html=True
        )


class TemplateCommentTests(TestCase):
    """Django only treats {# #} as a comment on a single line.

    A multi-line one renders straight onto the page, which is how a note to
    developers once ended up in front of the shopkeeper.
    """

    def setUp(self):
        self.client.force_login(make_user())

    def test_no_template_source_comments_leak_onto_rendered_pages(self):
        for url in [
            reverse("inventory:movements"),
            reverse("sales:history"),
            reverse("reports:sales"),
            reverse("core:dashboard"),
        ]:
            with self.subTest(url=url):
                body = self.client.get(url).content.decode()
                self.assertNotIn("{#", body)
                self.assertNotIn("{%", body)


class DateInputTests(TestCase):
    """<input type="date"> only accepts ISO-8601; anything else renders blank."""

    def setUp(self):
        self.user = make_user()
        self.product = make_product()
        stock_up(self.product, 10, self.user)
        self.client.force_login(self.user)

    def test_the_received_date_is_prefilled_in_a_format_the_browser_accepts(self):
        response = self.client.get(reverse("inventory:receive"))
        today = timezone.localdate().isoformat()
        self.assertContains(response, f'value="{today}"')

    def test_a_typed_date_survives_a_validation_error(self):
        expiry = (timezone.localdate() + timedelta(days=90)).isoformat()
        response = self.client.post(
            reverse("inventory:receive"),
            {
                "product": self.product.pk,
                "quantity": "",  # forces the form to redisplay
                "unit_cost": "10.00",
                "expiry_date": expiry,
                "batch_number": "LOT-1",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'value="{expiry}"')

    def test_the_product_form_expiry_field_also_round_trips(self):
        from apps.catalog.models import Category

        expiry = (timezone.localdate() + timedelta(days=30)).isoformat()
        response = self.client.post(
            reverse("catalog:product_create"),
            {
                "name": "Test",
                "sku": "",  # blank SKU forces redisplay
                "category": Category.objects.first().pk,
                "unit": "piece",
                "description": "",
                "cost_price": "1",
                "selling_price": "2",
                "minimum_stock": "1",
                "barcode": "",
                "is_active": "on",
                "opening_quantity": "5",
                "opening_expiry": expiry,
            },
        )
        self.assertContains(response, f'value="{expiry}"')
