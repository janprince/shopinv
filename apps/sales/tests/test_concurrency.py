"""Two tills, one shelf.

These use TransactionTestCase because they need real committed transactions
across threads — the thing being proved is that the database row lock, not luck,
is what keeps stock correct.
"""

from __future__ import annotations

import threading
from decimal import Decimal

from django.db import connections
from django.test import TransactionTestCase

from apps.core.tests.factories import make_product, make_user, stock_up
from apps.inventory.models import MovementType, StockMovement
from apps.inventory.services import InsufficientStock, adjust_stock
from apps.sales.models import Sale
from apps.sales.services import complete_sale


def run_in_threads(target, count):
    """Run ``target(index)`` in parallel and collect (result, error) per thread."""
    results = [None] * count
    barrier = threading.Barrier(count)

    def worker(index):
        try:
            barrier.wait(timeout=10)
            results[index] = ("ok", target(index))
        except Exception as exc:
            results[index] = ("error", exc)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    return results


class ConcurrentSaleTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.user = make_user()
        self.product = make_product()
        stock_up(self.product, 10, self.user)

    def test_two_tills_selling_at_once_never_oversell(self):
        """Ten in stock, two tills each asking for eight. Exactly one must win."""

        def sell(_index):
            return complete_sale(
                raw_lines=[{"product_id": self.product.pk, "quantity": "8"}], user=self.user
            )[0]

        results = run_in_threads(sell, 2)
        statuses = [status for status, _ in results]

        self.assertEqual(statuses.count("ok"), 1, f"expected one winner, got {results}")
        self.assertEqual(statuses.count("error"), 1)
        failure = next(value for status, value in results if status == "error")
        self.assertIsInstance(failure, InsufficientStock)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("2"))
        self.assertEqual(Sale.objects.count(), 1)

    def test_many_small_simultaneous_sales_all_add_up(self):
        def sell(_index):
            return complete_sale(
                raw_lines=[{"product_id": self.product.pk, "quantity": "1"}], user=self.user
            )[0]

        results = run_in_threads(sell, 5)
        self.assertEqual([status for status, _ in results].count("ok"), 5)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("5"))
        self.assertEqual(Sale.objects.count(), 5)
        self.assertEqual(len({sale.sale_number for sale in Sale.objects.all()}), 5)

    def test_the_ledger_still_reconciles_after_a_race(self):
        def sell(_index):
            return complete_sale(
                raw_lines=[{"product_id": self.product.pk, "quantity": "2"}], user=self.user
            )[0]

        run_in_threads(sell, 4)
        self.product.refresh_from_db()

        from django.db.models import Sum

        ledger = StockMovement.objects.filter(product=self.product).aggregate(
            total=Sum("quantity")
        )["total"]
        self.assertEqual(ledger, self.product.stock_quantity)

    def test_a_sale_and_a_write_off_at_the_same_time_stay_consistent(self):
        def act(index):
            if index == 0:
                return complete_sale(
                    raw_lines=[{"product_id": self.product.pk, "quantity": "6"}], user=self.user
                )[0]
            return adjust_stock(
                product=self.product,
                movement_type=MovementType.DAMAGED,
                quantity=Decimal("6"),
                reason="Dropped a crate",
                user=self.user,
            )

        results = run_in_threads(act, 2)
        self.assertEqual([status for status, _ in results].count("ok"), 1)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal("4"))
        self.assertGreaterEqual(self.product.stock_quantity, Decimal("0"))


class ConcurrentSaleNumberTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.user = make_user()
        self.products = [make_product(sku=f"P-{i}", name=f"Product {i}") for i in range(4)]
        for product in self.products:
            stock_up(product, 50, self.user)

    def test_simultaneous_sales_of_different_products_get_unique_numbers(self):
        def sell(index):
            return complete_sale(
                raw_lines=[{"product_id": self.products[index].pk, "quantity": "1"}],
                user=self.user,
            )[0]

        results = run_in_threads(sell, 4)
        self.assertEqual([status for status, _ in results].count("ok"), 4)
        self.assertEqual(Sale.objects.values("sale_number").distinct().count(), 4)

    def test_carts_holding_the_same_two_products_in_opposite_order_do_not_deadlock(self):
        """Lines are locked in a fixed order, so this pair can never deadlock."""
        first, second = self.products[0], self.products[1]

        def sell(index):
            order = [first, second] if index == 0 else [second, first]
            return complete_sale(
                raw_lines=[{"product_id": p.pk, "quantity": "1"} for p in order], user=self.user
            )[0]

        results = run_in_threads(sell, 2)
        self.assertEqual(
            [status for status, _ in results].count("ok"), 2, f"unexpected failure: {results}"
        )
