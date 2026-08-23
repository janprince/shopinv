import csv
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.tests.factories import make_owner, make_product, make_user, stock_up
from apps.inventory.models import MovementType
from apps.inventory.services import adjust_stock
from apps.reports import services as svc
from apps.sales.models import PaymentMethod
from apps.sales.services import complete_sale, reverse_sale


def read_csv(response):
    body = b"".join(response.streaming_content).decode("utf-8-sig")
    return list(csv.reader(body.splitlines()))


class ProfitCalculationTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.today = timezone.localdate()
        self.product = make_product(cost="10.00", price="25.00")
        stock_up(self.product, 100, self.user, cost="10.00")

    def test_gross_profit_is_revenue_minus_what_the_goods_cost(self):
        complete_sale(raw_lines=[{"product_id": self.product.pk, "quantity": "4"}], user=self.user)
        summary = svc.sales_summary(self.today, self.today)

        self.assertEqual(summary["revenue"], Decimal("100.00"))
        self.assertEqual(summary["cost"], Decimal("40.00"))
        self.assertEqual(summary["profit"], Decimal("60.00"))
        self.assertEqual(summary["units"], Decimal("4"))
        self.assertEqual(summary["count"], 1)

    def test_profit_uses_the_cost_at_the_time_of_sale_not_today(self):
        complete_sale(raw_lines=[{"product_id": self.product.pk, "quantity": "4"}], user=self.user)

        self.product.cost_price = Decimal("99.00")
        self.product.selling_price = Decimal("500.00")
        self.product.save()

        summary = svc.sales_summary(self.today, self.today)
        self.assertEqual(summary["profit"], Decimal("60.00"))

    def test_a_reversed_sale_is_excluded_from_every_figure(self):
        sale, _ = complete_sale(
            raw_lines=[{"product_id": self.product.pk, "quantity": "4"}], user=self.user
        )
        complete_sale(raw_lines=[{"product_id": self.product.pk, "quantity": "2"}], user=self.user)

        reverse_sale(sale=sale, user=make_owner(), reason="Wrong item sold")
        summary = svc.sales_summary(self.today, self.today)

        self.assertEqual(summary["count"], 1)
        self.assertEqual(summary["revenue"], Decimal("50.00"))
        self.assertEqual(summary["profit"], Decimal("30.00"))

    def test_the_margin_percentage_is_computed_from_revenue(self):
        complete_sale(raw_lines=[{"product_id": self.product.pk, "quantity": "4"}], user=self.user)
        summary = svc.sales_summary(self.today, self.today)
        self.assertEqual(summary["margin_percent"], Decimal("60"))

    def test_an_empty_period_returns_zeroes_rather_than_none(self):
        summary = svc.sales_summary(
            self.today - timedelta(days=90), self.today - timedelta(days=60)
        )
        self.assertEqual(summary["revenue"], Decimal("0"))
        self.assertEqual(summary["profit"], Decimal("0"))
        self.assertEqual(summary["count"], 0)
        self.assertIsNone(summary["margin_percent"])

    def test_write_offs_are_valued_at_cost(self):
        adjust_stock(
            product=self.product,
            movement_type=MovementType.DAMAGED,
            quantity=Decimal("3"),
            reason="Broken",
            user=self.user,
        )
        self.assertEqual(svc.stock_losses(self.today, self.today), Decimal("30.00"))


class InventoryReportTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.product = make_product(cost="10.00", price="25.00", minimum="5")

    def test_inventory_value_uses_each_batchs_own_cost(self):
        stock_up(self.product, 10, self.user, cost="10.00")
        stock_up(self.product, 10, self.user, cost="12.00")

        valuation = svc.inventory_value()
        self.assertEqual(valuation["cost_value"], Decimal("220.00"))
        self.assertEqual(valuation["retail_value"], Decimal("500.00"))
        self.assertEqual(valuation["potential_profit"], Decimal("280.00"))
        self.assertEqual(valuation["units"], Decimal("20"))

    def test_low_and_out_of_stock_lists_are_accurate(self):
        stock_up(self.product, 4, self.user)
        empty = make_product(name="Nothing Left", sku="NL-1")

        self.assertIn(self.product, list(svc.low_stock_products()))
        self.assertIn(empty, list(svc.out_of_stock_products()))
        self.assertIn(empty, list(svc.low_stock_products()))

    def test_expiring_and_expired_batches_are_separated(self):
        from apps.inventory.models import StockBatch

        today = timezone.localdate()
        stock_up(self.product, 5, self.user, expiry=today + timedelta(days=10))
        past = stock_up(self.product, 5, self.user, expiry=today + timedelta(days=1))
        StockBatch.objects.filter(pk=past.pk).update(expiry_date=today - timedelta(days=2))

        self.assertEqual(svc.expiring_batches(30).count(), 1)
        self.assertEqual(svc.expired_batches().count(), 1)

    def test_a_batch_that_is_used_up_stops_being_reported(self):
        today = timezone.localdate()
        stock_up(self.product, 5, self.user, expiry=today + timedelta(days=10))
        complete_sale(raw_lines=[{"product_id": self.product.pk, "quantity": "5"}], user=self.user)
        self.assertEqual(svc.expiring_batches(30).count(), 0)


class BreakdownTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.today = timezone.localdate()
        self.honey = make_product(sku="HON-500", cost="10.00", price="25.00")
        self.soap = make_product(name="Black Soap Bar", sku="SOAP-BLK", cost="2.00", price="5.00")
        stock_up(self.honey, 50, self.user, cost="10.00")
        stock_up(self.soap, 50, self.user, cost="2.00")

    def test_sales_by_product_ranks_correctly(self):
        complete_sale(raw_lines=[{"product_id": self.honey.pk, "quantity": "4"}], user=self.user)
        complete_sale(raw_lines=[{"product_id": self.soap.pk, "quantity": "10"}], user=self.user)

        rows = list(svc.sales_by_product(self.today, self.today))
        self.assertEqual(rows[0]["sku"], "HON-500")
        self.assertEqual(rows[0]["revenue"], Decimal("100.00"))
        self.assertEqual(rows[1]["revenue"], Decimal("50.00"))

        by_units = list(svc.sales_by_product(self.today, self.today, order="-units"))
        self.assertEqual(by_units[0]["sku"], "SOAP-BLK")

    def test_payment_breakdown_shares_add_up_to_a_hundred(self):
        complete_sale(
            raw_lines=[{"product_id": self.honey.pk, "quantity": "2"}],
            user=self.user,
            payment_method=PaymentMethod.CASH,
        )
        complete_sale(
            raw_lines=[{"product_id": self.honey.pk, "quantity": "2"}],
            user=self.user,
            payment_method=PaymentMethod.MOBILE_MONEY,
        )
        rows = svc.payment_breakdown(self.today, self.today)
        self.assertEqual(len(rows), 2)
        self.assertEqual(sum(row["share"] for row in rows), Decimal("100"))

    def test_the_daily_series_includes_days_with_no_sales(self):
        series = svc.daily_series(self.today - timedelta(days=4), self.today)
        self.assertEqual(len(series), 5)
        self.assertTrue(all("revenue" in row for row in series))

    def test_slow_movers_puts_the_never_sold_first(self):
        complete_sale(raw_lines=[{"product_id": self.honey.pk, "quantity": "10"}], user=self.user)
        rows = svc.slow_movers(self.today, self.today, limit=5)
        self.assertEqual(rows[0]["product"].sku, "SOAP-BLK")
        self.assertEqual(rows[0]["units"], Decimal("0"))


class CsvExportTests(TestCase):
    def setUp(self):
        self.owner = make_owner()
        self.keeper = make_user()
        self.product = make_product(cost="10.00", price="25.00")
        stock_up(self.product, 20, self.keeper, cost="10.00")
        complete_sale(
            raw_lines=[{"product_id": self.product.pk, "quantity": "3"}], user=self.keeper
        )
        adjust_stock(
            product=self.product,
            movement_type=MovementType.DAMAGED,
            quantity=Decimal("1"),
            reason="Broken bottle",
            user=self.keeper,
        )

    def _get(self, name, user):
        self.client.force_login(user)
        response = self.client.get(reverse(name))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("attachment;", response["Content-Disposition"])
        return read_csv(response)

    def test_every_export_downloads_with_a_header_and_rows(self):
        for name in [
            "catalog:product_export",
            "inventory:movements_export",
            "sales:history_export",
            "reports:sales_export",
            "reports:products_export",
            "reports:categories_export",
            "reports:payments_export",
            "reports:inventory_export",
            "reports:expiry_export",
            "reports:adjustments_export",
            "reports:profit_export",
            "core:audit_export",
        ]:
            with self.subTest(export=name):
                rows = self._get(name, self.owner)
                self.assertGreaterEqual(len(rows), 1)
                self.assertTrue(rows[0][0])

    def test_the_product_export_carries_the_real_figures(self):
        rows = self._get("catalog:product_export", self.owner)
        header, data = rows[0], rows[1]
        self.assertEqual(header[0], "SKU")
        self.assertEqual(data[0], "HON-500")
        self.assertEqual(data[6], "16")

    def test_the_sales_export_hides_profit_from_a_shopkeeper(self):
        owner_header = self._get("sales:history_export", self.owner)[0]
        keeper_header = self._get("sales:history_export", self.keeper)[0]
        self.assertIn("Estimated gross profit", owner_header)
        self.assertNotIn("Estimated gross profit", keeper_header)

    def test_a_shopkeeper_cannot_export_the_profit_report(self):
        self.client.force_login(self.keeper)
        self.assertEqual(self.client.get(reverse("reports:profit_export")).status_code, 403)

    def test_exports_respect_the_filters_on_screen(self):
        self.client.force_login(self.owner)
        response = self.client.get(
            reverse("inventory:movements_export"), {"movement_type": MovementType.DAMAGED}
        )
        rows = read_csv(response)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][4], "Damaged stock")

    def test_exporting_is_recorded_in_the_audit_history(self):
        from apps.core.models import AuditAction, AuditEvent

        self._get("sales:history_export", self.owner)
        self.assertTrue(AuditEvent.objects.filter(action=AuditAction.DATA_EXPORTED).exists())


class DashboardTests(TestCase):
    def setUp(self):
        self.owner = make_owner()
        self.keeper = make_user()
        self.product = make_product(cost="10.00", price="25.00", minimum="50")
        stock_up(self.product, 20, self.keeper, cost="10.00")
        complete_sale(
            raw_lines=[{"product_id": self.product.pk, "quantity": "3"}], user=self.keeper
        )

    def test_the_owner_sees_money_figures(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("core:dashboard"))
        self.assertContains(response, "Estimated profit today")
        self.assertContains(response, "Stock value (at cost)")

    def test_the_shopkeeper_does_not_see_profit_or_stock_value(self):
        self.client.force_login(self.keeper)
        response = self.client.get(reverse("core:dashboard"))
        self.assertNotContains(response, "Estimated profit today")
        self.assertNotContains(response, "Stock value (at cost)")

    def test_the_dashboard_flags_a_product_that_needs_restocking(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("core:dashboard"))
        self.assertContains(response, "Needs restocking")
        self.assertContains(response, self.product.name)

    def test_the_dashboard_shows_todays_takings(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("core:dashboard"))
        self.assertContains(response, "75.00")


class ProfitReportOrderingTests(TestCase):
    """The profit panel must rank by profit — its bars are scaled to the first row."""

    def setUp(self):
        self.owner = make_owner()
        high_revenue = make_product(
            name="Bulk Rice", sku="RICE-BULK", category=None, cost="90.00", price="100.00"
        )
        from apps.catalog.models import Category

        thin = Category.objects.create(name="Staples")
        fat = Category.objects.create(name="Remedies")
        high_revenue.category = thin
        high_revenue.save()
        high_margin = make_product(
            name="Moringa Powder", sku="MOR-200", category=fat, cost="5.00", price="40.00"
        )
        stock_up(high_revenue, 20, self.owner, cost="90.00")
        stock_up(high_margin, 20, self.owner, cost="5.00")

        # Staples earns more revenue; Remedies earns more profit.
        complete_sale(
            raw_lines=[{"product_id": high_revenue.pk, "quantity": "10"}], user=self.owner
        )
        complete_sale(raw_lines=[{"product_id": high_margin.pk, "quantity": "10"}], user=self.owner)

    def test_categories_are_ranked_by_profit_on_the_profit_report(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("reports:profit"), {"period": "today"})
        rows = response.context["by_category"]
        self.assertEqual(rows[0]["product__category__name"], "Remedies")
        profits = [row["profit"] for row in rows]
        self.assertEqual(profits, sorted(profits, reverse=True))

    def test_categories_are_still_ranked_by_revenue_on_the_category_report(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("reports:categories"), {"period": "today"})
        rows = response.context["rows"]
        self.assertEqual(rows[0]["product__category__name"], "Staples")
