"""Check that the cached stock figure still matches the batches behind it.

The cache is written inside the same transaction as every movement, so it should
never drift. This command exists so an operator can *prove* that, and repair it
if a manual database edit ever breaks the invariant.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Sum

from apps.catalog.models import Product
from apps.inventory.models import StockBatch, StockMovement
from apps.inventory.services import recalculate_product_stock


class Command(BaseCommand):
    help = "Compare each product's cached stock with its batches and its movement ledger."

    def add_arguments(self, parser):
        parser.add_argument("--fix", action="store_true", help="Repair any mismatch found.")

    def handle(self, *args, **options):
        batch_totals = dict(
            StockBatch.objects.values_list("product_id")
            .annotate(total=Sum("quantity_remaining"))
            .values_list("product_id", "total")
        )
        ledger_totals = dict(
            StockMovement.objects.values_list("product_id")
            .annotate(total=Sum("quantity"))
            .values_list("product_id", "total")
        )

        problems = 0
        for product in Product.objects.all().iterator():
            from decimal import Decimal

            cached = product.stock_quantity
            batches = batch_totals.get(product.pk) or Decimal("0")
            ledger = ledger_totals.get(product.pk) or Decimal("0")

            if cached == batches == ledger:
                continue

            problems += 1
            self.stderr.write(
                self.style.ERROR(
                    f"{product.sku} {product.name}: cached={cached} batches={batches} ledger={ledger}"
                )
            )
            if options["fix"]:
                repaired = recalculate_product_stock(product.pk)
                self.stdout.write(self.style.WARNING(f"  → cached value reset to {repaired}"))

        if problems == 0:
            self.stdout.write(
                self.style.SUCCESS("All products reconcile. Stock figures are sound.")
            )
        elif not options["fix"]:
            self.stdout.write(
                self.style.WARNING(f"{problems} mismatch(es). Re-run with --fix to repair.")
            )
        else:
            self.stdout.write(self.style.SUCCESS(f"Repaired {problems} product(s)."))
