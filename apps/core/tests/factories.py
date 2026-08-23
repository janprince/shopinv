"""Small builders so tests read as shop scenarios, not model soup."""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model

from apps.accounts.models import Role
from apps.catalog.models import Category, Product, Supplier, Unit
from apps.inventory.services import receive_stock

User = get_user_model()

DEFAULT_PASSWORD = "shop-pass-2026"


def make_user(username="kofi", role=Role.SHOPKEEPER, **kwargs):
    return User.objects.create_user(
        username=username,
        password=kwargs.pop("password", DEFAULT_PASSWORD),
        first_name=kwargs.pop("first_name", username.title()),
        role=role,
        **kwargs,
    )


def make_owner(username="ama", **kwargs):
    return make_user(username=username, role=Role.OWNER, **kwargs)


def make_category(name="Oils & spreads"):
    return Category.objects.get_or_create(name=name)[0]


def make_supplier(name="Kwahu Organic Farms"):
    return Supplier.objects.get_or_create(name=name)[0]


def make_product(
    name="Raw Wildflower Honey 500g",
    sku="HON-500",
    *,
    category=None,
    unit=Unit.BOTTLE,
    cost="38.00",
    price="58.00",
    minimum="6",
    **kwargs,
):
    return Product.objects.create(
        name=name,
        sku=sku,
        category=category or make_category(),
        unit=unit,
        cost_price=Decimal(cost),
        selling_price=Decimal(price),
        minimum_stock=Decimal(minimum),
        **kwargs,
    )


def stock_up(product, quantity, user, *, cost=None, expiry=None, batch_number="", opening=False):
    """Put stock on the shelf the only way the app allows: through a movement."""
    return receive_stock(
        product=product,
        quantity=Decimal(str(quantity)),
        unit_cost=Decimal(str(cost)) if cost is not None else product.cost_price,
        user=user,
        expiry_date=expiry,
        batch_number=batch_number,
        update_cost_price=False,
        opening=opening,
    )
