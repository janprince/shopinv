import json
import uuid
from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.urls import reverse

from apps.core.models import AuditAction, AuditEvent
from apps.core.tests.factories import make_owner, make_product, make_user, stock_up
from apps.inventory.models import MovementType, StockBatch, StockMovement
from apps.inventory.services import InsufficientStock
from apps.sales.models import PaymentMethod, Sale, SaleItem, SaleStatus
from apps.sales.services import SaleError, complete_sale, reverse_sale


class SaleCompletionTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.honey = make_product(sku="HON-500", cost="38.00", price="58.00")
        self.soap = make_product(name="Black Soap Bar", sku="SOAP-BLK", cost="6.50", price="12.00")
        stock_up(self.honey, 20, self.user, cost="38.00")
        stock_up(self.soap, 50, self.user, cost="6.50")

    def _sell(self, lines, **kwargs):
        return complete_sale(raw_lines=lines, user=self.user, **kwargs)

    def test_a_simple_sale_reduces_stock_exactly_once(self):
        sale, created = self._sell([{"product_id": self.honey.pk, "quantity": "2"}])
        self.assertTrue(created)
        self.honey.refresh_from_db()
        self.assertEqual(self.honey.stock_quantity, Decimal("18"))
        self.assertEqual(
            StockMovement.objects.filter(sale=sale, movement_type=MovementType.SALE).count(), 1
        )

    def test_the_sale_totals_are_correct(self):
        sale, _ = self._sell([{"product_id": self.honey.pk, "quantity": "2"}])
        self.assertEqual(sale.subtotal, Decimal("116.00"))
        self.assertEqual(sale.total, Decimal("116.00"))
        self.assertEqual(sale.cost_total, Decimal("76.00"))
        self.assertEqual(sale.gross_profit, Decimal("40.00"))

    def test_a_sale_with_several_items(self):
        sale, _ = self._sell(
            [
                {"product_id": self.honey.pk, "quantity": "2"},
                {"product_id": self.soap.pk, "quantity": "3"},
            ]
        )
        self.assertEqual(sale.items.count(), 2)
        self.assertEqual(sale.total, Decimal("152.00"))
        self.honey.refresh_from_db()
        self.soap.refresh_from_db()
        self.assertEqual(self.honey.stock_quantity, Decimal("18"))
        self.assertEqual(self.soap.stock_quantity, Decimal("47"))

    def test_the_same_product_listed_twice_is_merged_into_one_line(self):
        sale, _ = self._sell(
            [
                {"product_id": self.honey.pk, "quantity": "2"},
                {"product_id": self.honey.pk, "quantity": "3"},
            ]
        )
        self.assertEqual(sale.items.count(), 1)
        self.assertEqual(sale.items.first().quantity, Decimal("5"))
        self.honey.refresh_from_db()
        self.assertEqual(self.honey.stock_quantity, Decimal("15"))

    def test_prices_come_from_the_server_never_from_the_till(self):
        sale, _ = self._sell([{"product_id": self.honey.pk, "quantity": "1", "unit_price": "0.01"}])
        self.assertEqual(sale.items.first().unit_price, Decimal("58.00"))

    def test_selling_more_than_there_is_stops_the_whole_sale(self):
        with self.assertRaises(InsufficientStock):
            self._sell([{"product_id": self.honey.pk, "quantity": "21"}])

        self.honey.refresh_from_db()
        self.assertEqual(self.honey.stock_quantity, Decimal("20"))
        self.assertEqual(Sale.objects.count(), 0)
        self.assertEqual(SaleItem.objects.count(), 0)

    def test_one_bad_line_rolls_back_the_lines_that_would_have_worked(self):
        with self.assertRaises(InsufficientStock):
            self._sell(
                [
                    {"product_id": self.soap.pk, "quantity": "5"},
                    {"product_id": self.honey.pk, "quantity": "999"},
                ]
            )
        self.soap.refresh_from_db()
        self.assertEqual(self.soap.stock_quantity, Decimal("50"))
        self.assertEqual(Sale.objects.count(), 0)

    def test_an_empty_cart_is_refused(self):
        with self.assertRaises(SaleError):
            self._sell([])

    def test_zero_quantities_are_dropped_and_an_all_zero_cart_is_refused(self):
        with self.assertRaises(SaleError):
            self._sell([{"product_id": self.honey.pk, "quantity": "0"}])

    def test_an_inactive_product_cannot_be_sold(self):
        self.honey.is_active = False
        self.honey.save()
        with self.assertRaises(SaleError):
            self._sell([{"product_id": self.honey.pk, "quantity": "1"}])

    def test_sale_numbers_are_sequential_and_unique(self):
        numbers = [
            self._sell([{"product_id": self.soap.pk, "quantity": "1"}])[0].sale_number
            for _ in range(3)
        ]
        self.assertEqual(len(set(numbers)), 3)
        self.assertTrue(all(number.startswith("S") for number in numbers))
        self.assertEqual(sorted(numbers), numbers)

    def test_cash_change_is_calculated(self):
        sale, _ = self._sell(
            [{"product_id": self.honey.pk, "quantity": "1"}],
            payment_method=PaymentMethod.CASH,
            amount_received=Decimal("100.00"),
        )
        self.assertEqual(sale.change_due, Decimal("42.00"))

    def test_cash_less_than_the_total_is_refused(self):
        with self.assertRaises(SaleError):
            self._sell(
                [{"product_id": self.honey.pk, "quantity": "1"}],
                payment_method=PaymentMethod.CASH,
                amount_received=Decimal("10.00"),
            )

    def test_a_discount_comes_off_the_total_and_the_profit(self):
        sale, _ = self._sell(
            [{"product_id": self.honey.pk, "quantity": "2"}], discount=Decimal("16.00")
        )
        self.assertEqual(sale.subtotal, Decimal("116.00"))
        self.assertEqual(sale.total, Decimal("100.00"))
        self.assertEqual(sale.gross_profit, Decimal("24.00"))

    def test_a_discount_larger_than_the_sale_is_refused(self):
        with self.assertRaises(SaleError):
            self._sell([{"product_id": self.honey.pk, "quantity": "1"}], discount=Decimal("999"))

    def test_every_payment_method_is_accepted(self):
        for method in PaymentMethod.values:
            with self.subTest(method=method):
                sale, _ = self._sell(
                    [{"product_id": self.soap.pk, "quantity": "1"}], payment_method=method
                )
                self.assertEqual(sale.payment_method, method)

    def test_an_unknown_payment_method_is_refused(self):
        with self.assertRaises(SaleError):
            self._sell([{"product_id": self.soap.pk, "quantity": "1"}], payment_method="bitcoin")

    def test_completing_a_sale_is_audited(self):
        sale, _ = self._sell([{"product_id": self.honey.pk, "quantity": "1"}])
        event = AuditEvent.objects.get(action=AuditAction.SALE_COMPLETED)
        self.assertIn(sale.sale_number, event.summary)


class CostSnapshotTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.product = make_product(cost="10.00", price="20.00")

    def test_cost_comes_from_the_batch_actually_sold(self):
        stock_up(self.product, 5, self.user, cost="10.00")
        stock_up(self.product, 5, self.user, cost="14.00")

        sale, _ = complete_sale(
            raw_lines=[{"product_id": self.product.pk, "quantity": "5"}], user=self.user
        )
        item = sale.items.get()
        self.assertEqual(item.unit_cost, Decimal("10.00"))
        self.assertEqual(item.line_cost, Decimal("50.00"))
        self.assertEqual(item.gross_profit, Decimal("50.00"))

    def test_a_line_spanning_two_batches_uses_a_blended_cost(self):
        stock_up(self.product, 5, self.user, cost="10.00")
        stock_up(self.product, 5, self.user, cost="20.00")

        sale, _ = complete_sale(
            raw_lines=[{"product_id": self.product.pk, "quantity": "10"}], user=self.user
        )
        item = sale.items.get()
        self.assertEqual(item.line_cost, Decimal("150.00"))
        self.assertEqual(item.unit_cost, Decimal("15.00"))
        self.assertEqual(
            StockMovement.objects.filter(sale=sale, movement_type=MovementType.SALE).count(), 2
        )

    def test_changing_the_price_later_does_not_rewrite_history(self):
        stock_up(self.product, 10, self.user, cost="10.00")
        sale, _ = complete_sale(
            raw_lines=[{"product_id": self.product.pk, "quantity": "2"}], user=self.user
        )

        self.product.selling_price = Decimal("99.00")
        self.product.cost_price = Decimal("50.00")
        self.product.name = "Renamed Product"
        self.product.save()

        item = Sale.objects.get(pk=sale.pk).items.get()
        self.assertEqual(item.unit_price, Decimal("20.00"))
        self.assertEqual(item.unit_cost, Decimal("10.00"))
        self.assertEqual(item.product_name, "Raw Wildflower Honey 500g")
        sale.refresh_from_db()
        self.assertEqual(sale.total, Decimal("40.00"))
        self.assertEqual(sale.gross_profit, Decimal("20.00"))


class IdempotencyTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.product = make_product()
        stock_up(self.product, 20, self.user)

    def test_the_same_key_twice_records_only_one_sale(self):
        key = str(uuid.uuid4())
        lines = [{"product_id": self.product.pk, "quantity": "2"}]

        first, created_first = complete_sale(raw_lines=lines, user=self.user, idempotency_key=key)
        second, created_second = complete_sale(raw_lines=lines, user=self.user, idempotency_key=key)

        self.assertTrue(created_first)
        self.assertFalse(created_second)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Sale.objects.count(), 1)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("18"))

    def test_different_keys_record_separate_sales(self):
        lines = [{"product_id": self.product.pk, "quantity": "1"}]
        complete_sale(raw_lines=lines, user=self.user, idempotency_key=str(uuid.uuid4()))
        complete_sale(raw_lines=lines, user=self.user, idempotency_key=str(uuid.uuid4()))
        self.assertEqual(Sale.objects.count(), 2)

    def test_resubmitting_the_till_form_does_not_charge_twice(self):
        self.client.force_login(self.user)
        key = str(uuid.uuid4())
        payload = {
            "cart": json.dumps([{"product_id": self.product.pk, "quantity": "2"}]),
            "idempotency_key": key,
            "payment_method": PaymentMethod.CASH,
            "amount_received": "",
            "discount": "0",
            "payment_reference": "",
            "notes": "",
        }
        self.client.post(reverse("sales:pos"), payload)
        self.client.post(reverse("sales:pos"), payload)

        self.assertEqual(Sale.objects.count(), 1)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("18"))


class SaleImmutabilityTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.product = make_product()
        stock_up(self.product, 20, self.user)
        self.sale, _ = complete_sale(
            raw_lines=[{"product_id": self.product.pk, "quantity": "2"}], user=self.user
        )

    def test_a_completed_sale_cannot_be_deleted(self):
        with self.assertRaises(PermissionDenied):
            self.sale.delete()
        self.assertTrue(Sale.objects.filter(pk=self.sale.pk).exists())

    def test_a_sale_line_cannot_be_deleted(self):
        with self.assertRaises(PermissionDenied):
            self.sale.items.first().delete()

    def test_a_sales_movements_cannot_be_deleted(self):
        with self.assertRaises(PermissionDenied):
            StockMovement.objects.filter(sale=self.sale).first().delete()

    def test_there_is_no_url_that_deletes_a_sale(self):
        self.client.force_login(make_owner())
        for path in [f"/sales/{self.sale.pk}/delete/", f"/sales/{self.sale.pk}/remove/"]:
            self.assertEqual(self.client.post(path).status_code, 404)


class SaleReversalTests(TestCase):
    def setUp(self):
        self.owner = make_owner()
        self.keeper = make_user()
        self.product = make_product()
        stock_up(self.product, 20, self.keeper, cost="38.00", batch_number="ORIGINAL")
        self.sale, _ = complete_sale(
            raw_lines=[{"product_id": self.product.pk, "quantity": "5"}], user=self.keeper
        )

    def test_reversing_puts_the_stock_back(self):
        reverse_sale(sale=self.sale, user=self.owner, reason="Customer returned everything")
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("20"))

    def test_stock_returns_to_the_batch_it_came_from(self):
        batch = StockBatch.objects.get(batch_number="ORIGINAL")
        batch.refresh_from_db()
        self.assertEqual(batch.quantity_remaining, Decimal("15"))

        reverse_sale(sale=self.sale, user=self.owner, reason="Wrong item sold")
        batch.refresh_from_db()
        self.assertEqual(batch.quantity_remaining, Decimal("20"))

    def test_the_original_sale_and_its_movements_are_left_untouched(self):
        original_movements = list(
            StockMovement.objects.filter(sale=self.sale).values_list("pk", "quantity")
        )
        reverse_sale(sale=self.sale, user=self.owner, reason="Wrong item sold")

        still_there = list(
            StockMovement.objects.filter(
                sale=self.sale, movement_type=MovementType.SALE
            ).values_list("pk", "quantity")
        )
        self.assertEqual(original_movements, still_there)
        self.assertEqual(self.sale.items.count(), 1)

    def test_the_reversal_is_a_new_movement_with_the_reason_attached(self):
        reverse_sale(sale=self.sale, user=self.owner, reason="Customer changed their mind")
        movement = StockMovement.objects.get(movement_type=MovementType.SALE_REVERSAL)
        self.assertEqual(movement.quantity, Decimal("5"))
        self.assertEqual(movement.user, self.owner)
        self.assertIn("Customer changed their mind", movement.notes)

    def test_the_sale_is_marked_reversed_with_who_and_why(self):
        reverse_sale(sale=self.sale, user=self.owner, reason="Wrong item sold")
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.status, SaleStatus.REVERSED)
        self.assertEqual(self.sale.reversed_by, self.owner)
        self.assertEqual(self.sale.reversal_reason, "Wrong item sold")
        self.assertIsNotNone(self.sale.reversed_at)

    def test_a_sale_cannot_be_reversed_twice(self):
        reverse_sale(sale=self.sale, user=self.owner, reason="Wrong item sold")
        with self.assertRaises(SaleError):
            reverse_sale(sale=self.sale, user=self.owner, reason="Wrong item sold again")
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("20"))

    def test_a_reason_is_required(self):
        with self.assertRaises(SaleError):
            reverse_sale(sale=self.sale, user=self.owner, reason="no")

    def test_reversed_sales_stop_counting_towards_revenue(self):
        self.assertEqual(Sale.objects.counted().count(), 1)
        reverse_sale(sale=self.sale, user=self.owner, reason="Wrong item sold")
        self.assertEqual(Sale.objects.counted().count(), 0)

    def test_reversing_is_audited(self):
        reverse_sale(sale=self.sale, user=self.owner, reason="Wrong item sold")
        self.assertTrue(AuditEvent.objects.filter(action=AuditAction.SALE_REVERSED).exists())

    def test_a_shopkeeper_cannot_reverse_a_sale(self):
        self.client.force_login(self.keeper)
        response = self.client.post(
            reverse("sales:reverse", args=[self.sale.pk]),
            {"reason": "I want the money back", "confirm": "on"},
        )
        self.assertEqual(response.status_code, 403)
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.status, SaleStatus.COMPLETED)

    def test_an_owner_reverses_through_the_form(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("sales:reverse", args=[self.sale.pk]),
            {"reason": "Customer returned everything", "confirm": "on"},
        )
        self.assertRedirects(response, self.sale.get_absolute_url())
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.status, SaleStatus.REVERSED)

    def test_the_form_refuses_a_reversal_without_the_confirmation_tick(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("sales:reverse", args=[self.sale.pk]), {"reason": "Wrong item sold"}
        )
        self.assertEqual(response.status_code, 200)
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.status, SaleStatus.COMPLETED)


class PointOfSaleViewTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.product = make_product()
        stock_up(self.product, 10, self.user)
        self.client.force_login(self.user)

    def _payload(self, quantity="2", **overrides):
        payload = {
            "cart": json.dumps([{"product_id": self.product.pk, "quantity": quantity}]),
            "idempotency_key": str(uuid.uuid4()),
            "payment_method": PaymentMethod.CASH,
            "amount_received": "",
            "discount": "0",
            "payment_reference": "",
            "notes": "",
        }
        payload.update(overrides)
        return payload

    def test_the_till_opens_with_the_search_box_focused(self):
        response = self.client.get(reverse("sales:pos"))
        self.assertContains(response, 'data-autofocus="true"')
        self.assertContains(response, 'id="pos-search"')

    def test_a_sale_posts_through_and_lands_on_the_success_page(self):
        response = self.client.post(reverse("sales:pos"), self._payload())
        sale = Sale.objects.get()
        self.assertRedirects(response, reverse("sales:complete", args=[sale.pk]))

    def test_the_success_page_offers_the_next_sale_and_a_receipt(self):
        self.client.post(reverse("sales:pos"), self._payload())
        sale = Sale.objects.get()
        response = self.client.get(reverse("sales:complete", args=[sale.pk]))
        self.assertContains(response, "Start the next sale")
        self.assertContains(response, "Print receipt")

    def test_stock_running_out_mid_sale_produces_a_clear_message_and_keeps_the_cart(self):
        response = self.client.post(reverse("sales:pos"), self._payload(quantity="99"), follow=True)
        self.assertContains(response, "Not enough")
        self.assertContains(response, "was not recorded")
        self.assertContains(response, f'"product_id": {self.product.pk}')
        self.assertEqual(Sale.objects.count(), 0)

    def test_search_finds_a_product_by_name_and_by_code(self):
        for term in ("honey", "HON-500"):
            with self.subTest(term=term):
                response = self.client.get(reverse("sales:product_search"), {"q": term})
                self.assertContains(response, self.product.name)

    def test_search_marks_an_out_of_stock_product_as_unavailable(self):
        make_product(name="Sold Out Item", sku="OUT-1")
        response = self.client.get(reverse("sales:product_search"), {"q": "Sold Out"})
        self.assertContains(response, "Out of stock")
        self.assertContains(response, "disabled")

    def test_the_receipt_prints_without_the_app_furniture(self):
        self.client.post(reverse("sales:pos"), self._payload())
        sale = Sale.objects.get()
        response = self.client.get(reverse("sales:receipt", args=[sale.pk]))
        self.assertContains(response, sale.sale_number)
        self.assertNotContains(response, "sidebar")

    def test_a_reversed_sale_receipt_says_so_loudly(self):
        self.client.post(reverse("sales:pos"), self._payload())
        sale = Sale.objects.get()
        reverse_sale(sale=sale, user=make_owner(), reason="Wrong item sold")
        response = self.client.get(reverse("sales:receipt", args=[sale.pk]))
        self.assertContains(response, "NOT A VALID SALE")
