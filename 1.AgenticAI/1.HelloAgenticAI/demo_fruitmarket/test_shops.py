"""Unit tests for the six fruit-shop tools and the registration helper."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from demo_fruitmarket.schemas import (
    BasketItem,
    ShopRequest,
    ShopResponse,
)
from demo_fruitmarket.shops import (
    ALL_SHOP_CLASSES,
    AppleOrchard,
    BerryBasket,
    CitrusGrove,
    FruitShopToolBase,
    GlobalImports,
    StoneFruitStand,
    TropicalParadise,
    register_all_shops,
)
from framework.tools.base import ToolRegistry

# ---------- helpers ----------


def _basket(*items: tuple[str, int]) -> ShopRequest:
    return ShopRequest(basket=[BasketItem(sku=sku, quantity=qty) for sku, qty in items])


# ---------- schema validation ----------


def test_basket_item_rejects_negative_quantity() -> None:
    with pytest.raises(ValidationError):
        BasketItem(sku="apple", quantity=0)


def test_basket_item_rejects_empty_sku() -> None:
    with pytest.raises(ValidationError):
        BasketItem(sku="", quantity=1)


def test_shop_request_rejects_empty_basket() -> None:
    with pytest.raises(ValidationError):
        ShopRequest(basket=[])


# ---------- FruitShopToolBase contract ----------


def test_all_six_shop_classes_register_with_unique_names() -> None:
    reg = ToolRegistry()
    register_all_shops(reg)
    assert len(reg) == 6
    assert reg.names() == sorted(s.SHOP_NAME for s in ALL_SHOP_CLASSES)


def test_each_shop_implements_mcp_tool_protocol() -> None:
    for shop_cls in ALL_SHOP_CLASSES:
        shop = shop_cls()
        assert isinstance(shop, FruitShopToolBase)
        assert shop.name
        assert shop.description
        assert shop.input_schema is ShopRequest
        assert shop.output_schema is ShopResponse


def test_descriptors_round_trip_to_json_schema() -> None:
    shop = AppleOrchard()
    d = shop.to_router_descriptor()
    assert d["name"] == "apple_orchard"
    assert "apples" in d["description"].lower()
    assert d["input_schema"]["properties"]["basket"]["type"] == "array"


# ---------- happy path: all in stock ----------


async def test_apple_orchard_all_in_stock() -> None:
    shop = AppleOrchard()
    resp = await shop.call(
        _basket(("apple_gala", 3), ("pear_bartlett", 2)),
    )
    assert resp.shop_name == "apple_orchard"
    assert {p.sku for p in resp.purchased} == {"apple_gala", "pear_bartlett"}
    assert resp.out_of_stock == []
    assert resp.rationed == []
    # 3 * 0.80 + 2 * 1.10 = 2.40 + 2.20 = 4.60
    assert resp.total_price == 4.60


async def test_stone_fruit_stand_all_in_stock() -> None:
    shop = StoneFruitStand()
    resp = await shop.call(_basket(("peach", 4), ("cherry_bing", 1)))
    assert {p.quantity for p in resp.purchased} == {4, 1}
    assert resp.out_of_stock == []


# ---------- out_of_stock path ----------


async def test_unknown_sku_appears_in_out_of_stock() -> None:
    """The agent might ask a shop for an SKU it doesn't carry — surfaces as OOS."""
    shop = AppleOrchard()
    resp = await shop.call(_basket(("durian", 1)))
    assert resp.purchased == []
    assert resp.out_of_stock == ["durian"]
    assert resp.total_price == 0.0


async def test_in_stock_false_appears_in_out_of_stock() -> None:
    """An SKU the shop carries but is currently out of also surfaces as OOS."""
    shop = CitrusGrove()
    resp = await shop.call(_basket(("grapefruit", 2)))
    assert resp.purchased == []
    assert resp.out_of_stock == ["grapefruit"]


async def test_pineapple_is_out_at_tropical_paradise() -> None:
    """Canonical replan trigger — exercise the OOS replan path's trigger event."""
    shop = TropicalParadise()
    resp = await shop.call(_basket(("pineapple", 1)))
    assert resp.purchased == []
    assert resp.out_of_stock == ["pineapple"]


async def test_strawberries_oos_at_berry_basket_and_no_other_shop_has_them() -> None:
    """Hard-fail path the reflector must terminate cleanly on."""
    berry = await BerryBasket().call(_basket(("strawberries", 1)))
    assert berry.out_of_stock == ["strawberries"]
    # No other shop has strawberries in inventory at all
    for shop_cls in ALL_SHOP_CLASSES:
        if shop_cls is BerryBasket:
            continue
        shop = shop_cls()
        resp = await shop.call(_basket(("strawberries", 1)))
        assert resp.out_of_stock == ["strawberries"]


# ---------- rationed path ----------


async def test_dragon_fruit_at_tropical_paradise_is_rationed() -> None:
    """Rationing — request 5, get max 2, agent must source remainder elsewhere."""
    shop = TropicalParadise()
    resp = await shop.call(_basket(("dragon_fruit", 5)))
    assert len(resp.purchased) == 1
    line = resp.purchased[0]
    assert line.sku == "dragon_fruit"
    assert line.quantity == 2  # rationed down from 5
    assert resp.rationed == ["dragon_fruit"]
    # Price reflects the actual purchased quantity
    assert resp.total_price == 7.00  # 2 * 3.50


async def test_rationed_only_triggers_at_or_above_max_qty() -> None:
    """Requesting at or below max_qty is NOT rationing."""
    shop = TropicalParadise()
    resp = await shop.call(_basket(("dragon_fruit", 2)))
    assert resp.rationed == []
    assert resp.purchased[0].quantity == 2


async def test_global_imports_dragon_fruit_unrationed() -> None:
    """The fallback shop carries dragon_fruit unlimited (more expensive)."""
    shop = GlobalImports()
    resp = await shop.call(_basket(("dragon_fruit", 10)))
    assert resp.rationed == []
    assert resp.purchased[0].quantity == 10
    # 10 * 5.50 = 55.00
    assert resp.total_price == 55.00


# ---------- mixed: some in stock, some out, some rationed ----------


async def test_tropical_paradise_mixed_basket() -> None:
    """Realistic agent call — multiple items at once, some succeed, some not."""
    shop = TropicalParadise()
    resp = await shop.call(
        _basket(
            ("mango_alphonso", 2),  # in stock → purchased
            ("pineapple", 1),  # OOS → out_of_stock
            ("dragon_fruit", 5),  # rationed → 2 purchased + on rationed list
            ("durian", 1),  # not stocked → out_of_stock
        )
    )
    purchased_skus = {p.sku for p in resp.purchased}
    assert purchased_skus == {"mango_alphonso", "dragon_fruit"}
    assert set(resp.out_of_stock) == {"pineapple", "durian"}
    assert resp.rationed == ["dragon_fruit"]
    # 2 * 2.50 + 2 * 3.50 = 5.00 + 7.00 = 12.00
    assert resp.total_price == 12.00


# ---------- replan scenario reproducible ----------


async def test_canonical_replan_pineapple_tropical_then_global_imports() -> None:
    """Reproducible scripted replan for the demo's flagship case."""
    # Step 1: try tropical_paradise for pineapple — OOS
    tropical = TropicalParadise()
    first = await tropical.call(_basket(("pineapple", 1)))
    assert "pineapple" in first.out_of_stock

    # Step 2: agent replans → tries global_imports, succeeds
    imports_shop = GlobalImports()
    second = await imports_shop.call(_basket(("pineapple", 1)))
    assert second.out_of_stock == []
    assert len(second.purchased) == 1
    assert second.purchased[0].sku == "pineapple"
    assert second.purchased[0].unit_price == 8.00


# ---------- inventory consistency ----------


def test_inventory_dicts_have_no_overlapping_skus_with_inconsistent_pricing() -> None:
    """If two shops carry the same SKU, their prices may differ (intentional —
    shops compete) but neither should be 0 nor negative."""
    sku_to_prices: dict[str, list[tuple[str, float]]] = {}
    for shop_cls in ALL_SHOP_CLASSES:
        for sku, entry in shop_cls.INVENTORY.items():
            sku_to_prices.setdefault(sku, []).append((shop_cls.SHOP_NAME, entry.unit_price))
            assert entry.unit_price > 0, f"{shop_cls.SHOP_NAME}.{sku} has non-positive price"

    # dragon_fruit and pineapple are intentionally carried by two shops
    overlapping = {sku for sku, prices in sku_to_prices.items() if len(prices) > 1}
    assert overlapping == {"dragon_fruit", "pineapple"}
