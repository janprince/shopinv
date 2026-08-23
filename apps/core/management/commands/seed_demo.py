"""Fill an empty database with believable demo data.

Useful for trying the app out, for screenshots and for training a new shopkeeper
without touching real figures.
"""

from __future__ import annotations

import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Role
from apps.catalog.models import Category, Product, Supplier, Unit
from apps.core.models import ShopSettings
from apps.inventory.models import MovementType
from apps.inventory.services import StockError, adjust_stock, receive_stock
from apps.sales.models import PaymentMethod, Sale
from apps.sales.services import complete_sale

User = get_user_model()

CATEGORIES = [
    ("Fresh produce", "Fruit and vegetables from local farms"),
    ("Grains & flours", "Rice, millet, cassava and wheat products"),
    ("Oils & spreads", "Cooking oils, nut butters and honey"),
    ("Drinks", "Juices, teas and bottled water"),
    ("Personal care", "Soaps, butters and natural skincare"),
    ("Household", "Cleaning and kitchen essentials"),
]

SUPPLIERS = [
    ("Kwahu Organic Farms", "024 411 2233", "Kwahu, Eastern Region"),
    ("Accra Wholesale Foods", "030 277 4410", "Kaneshie, Accra"),
    ("Shea Sisters Collective", "020 998 3311", "Tamale, Northern Region"),
    ("Volta Fresh Produce", "054 220 7788", "Ho, Volta Region"),
]

PRODUCTS = [
    # name, sku, category index, unit, cost, price, min stock, expires
    ("Raw Wildflower Honey 500g", "HON-500", 2, Unit.BOTTLE, "38.00", "58.00", 6, True),
    ("Cold-Pressed Coconut Oil 500ml", "COC-500", 2, Unit.BOTTLE, "42.00", "65.00", 6, True),
    ("Shea Butter 250g", "SHEA-250", 4, Unit.PIECE, "18.00", "32.00", 10, True),
    ("Black Soap Bar", "SOAP-BLK", 4, Unit.PIECE, "6.50", "12.00", 20, False),
    ("Brown Rice", "RICE-BRN", 1, Unit.KILOGRAM, "14.00", "22.00", 15, True),
    ("Millet Flour", "FLR-MIL", 1, Unit.KILOGRAM, "11.00", "18.50", 10, True),
    ("Cassava Gari (fine)", "GARI-FIN", 1, Unit.KILOGRAM, "9.00", "15.00", 20, True),
    ("Hibiscus Tea 100g", "TEA-HIB", 3, Unit.PACK, "12.00", "22.00", 8, True),
    ("Fresh Ginger", "PRD-GIN", 0, Unit.KILOGRAM, "10.00", "18.00", 5, True),
    ("Ripe Plantain", "PRD-PLT", 0, Unit.PIECE, "1.80", "3.50", 30, True),
    ("Avocado", "PRD-AVO", 0, Unit.PIECE, "3.00", "6.00", 20, True),
    ("Baobab Juice 1L", "JUI-BAO", 3, Unit.BOTTLE, "16.00", "28.00", 8, True),
    ("Bottled Spring Water 1.5L", "WTR-1500", 3, Unit.BOTTLE, "3.20", "6.00", 40, False),
    ("Neem Toothpaste", "PC-NEEM", 4, Unit.PIECE, "14.00", "24.00", 10, True),
    ("Coconut Fibre Sponge", "HH-SPNG", 5, Unit.PIECE, "4.00", "8.00", 25, False),
    ("Beeswax Food Wrap (3 pack)", "HH-WRAP", 5, Unit.PACK, "26.00", "45.00", 6, False),
    ("Groundnut Paste 400g", "PST-GND", 2, Unit.BOTTLE, "15.00", "26.00", 8, True),
    ("Moringa Powder 200g", "PWD-MOR", 4, Unit.SACHET, "22.00", "38.00", 8, True),
]


class Command(BaseCommand):
    help = "Load demo products, stock and sales. Refuses to run on a database that has sales."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days", type=int, default=45, help="How many days of sales to invent."
        )
        parser.add_argument("--force", action="store_true", help="Run even if sales already exist.")

    def handle(self, *args, **options):
        if Sale.objects.exists() and not options["force"]:
            raise CommandError(
                "This database already has sales in it. Refusing to add demo data.\n"
                "Pass --force only if you are certain this is a throwaway database."
            )

        random.seed(20260822)
        shop = ShopSettings.load()
        shop.shop_name = "JCF Organic"
        shop.tagline = "Natural & organic goods"
        shop.phone = "030 296 1180"
        shop.email = "hello@jcforganic.example"
        shop.address = "12 Ring Road East\nOsu, Accra"
        shop.save()

        owner = self._ensure_user("ama", "Ama", "Boateng", Role.OWNER)
        keeper = self._ensure_user("kofi", "Kofi", "Mensah", Role.SHOPKEEPER)
        staff = [owner, keeper]

        with transaction.atomic():
            categories = [
                Category.objects.get_or_create(name=name, defaults={"description": description})[0]
                for name, description in CATEGORIES
            ]
            suppliers = [
                Supplier.objects.get_or_create(
                    name=name, defaults={"phone": phone, "location": location}
                )[0]
                for name, phone, location in SUPPLIERS
            ]

            products = []
            for name, sku, cat_index, unit, cost, price, minimum, expires in PRODUCTS:
                product, created = Product.objects.get_or_create(
                    sku=sku,
                    defaults={
                        "name": name,
                        "category": categories[cat_index],
                        "unit": unit,
                        "cost_price": Decimal(cost),
                        "selling_price": Decimal(price),
                        "minimum_stock": Decimal(minimum),
                    },
                )
                products.append((product, expires, created))

        now = timezone.localtime()
        days = options["days"]

        # Opening stock, dated at the start of the demo period.
        for product, expires, created in products:
            if not created:
                continue
            quantity = Decimal(random.randint(20, 90))
            if product.unit in {Unit.KILOGRAM, Unit.LITRE}:
                quantity = Decimal(random.randint(15, 60))
            receive_stock(
                product=product,
                quantity=quantity,
                unit_cost=product.cost_price,
                user=owner,
                supplier=random.choice(suppliers),
                batch_number=f"OPEN-{product.sku}",
                expiry_date=(now + timedelta(days=random.randint(20, 300))).date()
                if expires
                else None,
                notes="Opening stock at the start of the demo period.",
                received_at=now - timedelta(days=days),
                update_cost_price=False,
                opening=True,
            )

        self.stdout.write(f"Recording {days} days of activity…")

        for offset in range(days, -1, -1):
            day = now - timedelta(days=offset)

            # Restock every few days.
            if offset % 6 == 0:
                for product, expires, _created in random.sample(products, 4):
                    receive_stock(
                        product=product,
                        quantity=Decimal(random.randint(10, 40)),
                        unit_cost=(
                            product.cost_price * Decimal(random.choice(["0.95", "1.0", "1.05"]))
                        ).quantize(Decimal("0.01")),
                        user=random.choice(staff),
                        supplier=random.choice(suppliers),
                        batch_number=f"B{day:%y%m%d}-{product.sku[:4]}",
                        expiry_date=(day + timedelta(days=random.randint(30, 400))).date()
                        if expires
                        else None,
                        received_at=min(day.replace(hour=8, minute=random.randint(0, 50)), now),
                    )

            # Sundays are quiet.
            sale_count = random.randint(2, 5) if day.weekday() == 6 else random.randint(5, 14)
            for _ in range(sale_count):
                lines = []
                for product, _expires, _created in random.sample(products, random.randint(1, 4)):
                    product.refresh_from_db()
                    if product.stock_quantity <= 1:
                        continue
                    top = min(int(product.stock_quantity), 4)
                    lines.append(
                        {"product_id": product.pk, "quantity": random.randint(1, max(1, top))}
                    )
                if not lines:
                    continue

                method = random.choices(
                    [PaymentMethod.CASH, PaymentMethod.MOBILE_MONEY, PaymentMethod.BANK_TRANSFER],
                    weights=[62, 33, 5],
                )[0]
                try:
                    sale, _created = complete_sale(
                        raw_lines=lines,
                        user=random.choice(staff),
                        payment_method=method,
                        idempotency_key=None,
                    )
                except StockError:
                    # A demo basket that no longer fits the shelf — skip it and move on.
                    continue
                Sale.objects.filter(pk=sale.pk).update(completed_at=self._shop_hour(day, now))

            # The occasional breakage or count correction.
            if offset % 9 == 0:
                product, _expires, _created = random.choice(products)
                product.refresh_from_db()
                if product.stock_quantity >= 3:
                    adjust_stock(
                        product=product,
                        movement_type=random.choice(
                            [MovementType.DAMAGED, MovementType.MISSING, MovementType.EXPIRED]
                        ),
                        quantity=Decimal(random.randint(1, 3)),
                        reason=random.choice(
                            [
                                "Broken in transit",
                                "Not found during stock count",
                                "Past expiry, removed from shelf",
                                "Damaged packaging",
                            ]
                        ),
                        user=random.choice(staff),
                    )

        self.stdout.write(self.style.SUCCESS("Demo data loaded."))
        self.stdout.write("  Owner:      ama   / demo-pass-2026")
        self.stdout.write("  Shopkeeper: kofi  / demo-pass-2026")
        self.stdout.write(
            self.style.WARNING("Change these passwords before using the app for real.")
        )

    @staticmethod
    def _shop_hour(day, now):
        """A plausible moment during opening hours, never in the future.

        Without the clamp, seeding shortly after midnight puts the whole of
        "today" in the future and the dashboard opens showing no sales at all.
        """
        moment = day.replace(
            hour=random.randint(8, 18), minute=random.randint(0, 59), second=0, microsecond=0
        )
        if moment <= now:
            return moment
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elapsed = max(int((now - midnight).total_seconds()) - 1, 1)
        return now - timedelta(seconds=random.randint(0, elapsed))

    def _ensure_user(self, username, first, last, role):
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "first_name": first,
                "last_name": last,
                "role": role,
                "email": f"{username}@jcforganic.example",
            },
        )
        if created:
            user.set_password("demo-pass-2026")
            user.save()
        return user
