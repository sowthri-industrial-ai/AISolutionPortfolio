"""Six mock fruit-shop :class:`MCPToolBase` subclasses with deliberately
varied inventories.

Each shop is registered as one tool in the agent's :class:`ToolRegistry`.
Inventories are class-level constants (NamedTuple) so the data is
auditable at a glance — reviewing a shop is one block of code.

Designed-in conditions that exercise the framework's loop:

* ``citrus_grove.grapefruit`` is **out of season** — agent gets
  ``out_of_stock``, must replan.
* ``tropical_paradise.pineapple`` is **out of season** — same.
* ``tropical_paradise.dragon_fruit`` is **rationed** (max 2 per visit) —
  agent gets a partial purchase, must replan for the remainder.
* ``berry_basket.strawberries`` is **off-season**, and **no other shop
  stocks them** — agent must terminate with a partial basket.
* ``global_imports`` carries everything tropical but is **expensive** —
  router prefers it as a fallback, not as the first choice.
"""

from __future__ import annotations

from typing import ClassVar, NamedTuple

from demo_fruitmarket.schemas import (
    PurchasedLine,
    ShopRequest,
    ShopResponse,
)
from framework.tools.base import MCPToolBase, ToolRegistry


class StockEntry(NamedTuple):
    """Inventory entry — price + availability + optional rationing.

    ``in_stock=False`` means the shop carries this SKU but is currently
    out of it (out of season, sold out, etc.) — surfaces as
    ``out_of_stock``. A SKU **not present** in the inventory dict means
    the shop doesn't carry it at all — also surfaces as ``out_of_stock``.
    The agent doesn't need to distinguish.

    ``max_qty=N`` rations the SKU: a request for >N of this SKU returns N
    in ``purchased`` AND adds the SKU to ``rationed`` so the agent knows
    to source the remainder elsewhere.
    """

    unit_price: float
    in_stock: bool = True
    max_qty: int | None = None


class FruitShopToolBase(MCPToolBase[ShopRequest, ShopResponse]):
    """Shared logic for all fruit-shop tools.

    Subclasses override the three :py:obj:`ClassVar` constants
    ``SHOP_NAME``, ``SHOP_DESCRIPTION``, ``INVENTORY``. The base class
    implements the abstract :class:`MCPToolBase` properties + ``call()``.

    Concrete subclasses are not themselves abstract; instantiating
    :class:`FruitShopToolBase` directly raises ``AttributeError`` on the
    first property access (because the ClassVars have no defaults).
    """

    SHOP_NAME: ClassVar[str]
    SHOP_DESCRIPTION: ClassVar[str]
    INVENTORY: ClassVar[dict[str, StockEntry]]

    @property
    def name(self) -> str:
        return self.SHOP_NAME

    @property
    def description(self) -> str:
        return self.SHOP_DESCRIPTION

    @property
    def input_schema(self) -> type[ShopRequest]:
        return ShopRequest

    @property
    def output_schema(self) -> type[ShopResponse]:
        return ShopResponse

    async def call(self, payload: ShopRequest) -> ShopResponse:
        purchased: list[PurchasedLine] = []
        out_of_stock: list[str] = []
        rationed: list[str] = []
        total = 0.0

        for item in payload.basket:
            entry = self.INVENTORY.get(item.sku)
            if entry is None or not entry.in_stock:
                out_of_stock.append(item.sku)
                continue

            qty_to_sell = item.quantity
            if entry.max_qty is not None and item.quantity > entry.max_qty:
                qty_to_sell = entry.max_qty
                rationed.append(item.sku)

            line_total = round(qty_to_sell * entry.unit_price, 2)
            purchased.append(
                PurchasedLine(
                    sku=item.sku,
                    quantity=qty_to_sell,
                    unit_price=entry.unit_price,
                    line_total=line_total,
                )
            )
            total += line_total

        return ShopResponse(
            shop_name=self.SHOP_NAME,
            purchased=purchased,
            out_of_stock=out_of_stock,
            rationed=rationed,
            total_price=round(total, 2),
        )


# ---------- the six shops ----------


class AppleOrchard(FruitShopToolBase):
    """Cheapest shop. All in stock."""

    SHOP_NAME = "apple_orchard"
    SHOP_DESCRIPTION = (
        "Apples (gala, fuji, granny_smith) and pears (bartlett, anjou). "
        "Family farm, all in season, cheapest in the market."
    )
    INVENTORY: ClassVar[dict[str, StockEntry]] = {
        "apple_gala": StockEntry(unit_price=0.80),
        "apple_fuji": StockEntry(unit_price=0.85),
        "apple_granny_smith": StockEntry(unit_price=0.75),
        "pear_bartlett": StockEntry(unit_price=1.10),
        "pear_anjou": StockEntry(unit_price=1.20),
    }


class CitrusGrove(FruitShopToolBase):
    """Citrus only. Grapefruit out of season — exercises out_of_stock path."""

    SHOP_NAME = "citrus_grove"
    SHOP_DESCRIPTION = "Oranges (navel, blood), lemons, limes. Grapefruit currently out of season."
    INVENTORY: ClassVar[dict[str, StockEntry]] = {
        "orange_navel": StockEntry(unit_price=0.70),
        "orange_blood": StockEntry(unit_price=1.10),
        "lemon": StockEntry(unit_price=0.50),
        "lime": StockEntry(unit_price=0.45),
        "grapefruit": StockEntry(unit_price=1.30, in_stock=False),
    }


class TropicalParadise(FruitShopToolBase):
    """Affordable tropical fruits. Pineapple OOS, dragon_fruit rationed."""

    SHOP_NAME = "tropical_paradise"
    SHOP_DESCRIPTION = (
        "Mangoes (alphonso, ataulfo), papayas, dragon fruit. Affordable tropical "
        "fruits. Pineapples currently out of season; dragon fruit limited stock "
        "(max 2 per visit)."
    )
    INVENTORY: ClassVar[dict[str, StockEntry]] = {
        "mango_alphonso": StockEntry(unit_price=2.50),
        "mango_ataulfo": StockEntry(unit_price=2.00),
        "papaya": StockEntry(unit_price=2.80),
        "dragon_fruit": StockEntry(unit_price=3.50, max_qty=2),
        "pineapple": StockEntry(unit_price=4.00, in_stock=False),
    }


class BerryBasket(FruitShopToolBase):
    """Berries. Strawberries off-season — and no other shop has them."""

    SHOP_NAME = "berry_basket"
    SHOP_DESCRIPTION = (
        "Blueberries, raspberries, blackberries — fresh-picked. Strawberries are off-season."
    )
    INVENTORY: ClassVar[dict[str, StockEntry]] = {
        "blueberry": StockEntry(unit_price=4.00),
        "raspberry": StockEntry(unit_price=4.50),
        "blackberry": StockEntry(unit_price=4.20),
        "strawberry": StockEntry(unit_price=3.80, in_stock=False),
    }


class StoneFruitStand(FruitShopToolBase):
    """Stone fruits, all in stock. Happy-path shop for stone fruit goals."""

    SHOP_NAME = "stone_fruit_stand"
    SHOP_DESCRIPTION = (
        "Peaches, plums, cherries (bing, rainier), nectarines. All in stock, fair prices."
    )
    INVENTORY: ClassVar[dict[str, StockEntry]] = {
        "peach": StockEntry(unit_price=1.50),
        "plum": StockEntry(unit_price=1.20),
        "cherry_bing": StockEntry(unit_price=2.00),
        "cherry_rainier": StockEntry(unit_price=2.50),
        "nectarine": StockEntry(unit_price=1.60),
    }


class GlobalImports(FruitShopToolBase):
    """Premium tropical fruits — fallback when other shops are out. Pricey."""

    SHOP_NAME = "global_imports"
    SHOP_DESCRIPTION = (
        "Premium imported tropical fruits — pineapples, durian, lychee, "
        "mangosteen, rambutan, dragon fruit. Always in stock but expensive."
    )
    INVENTORY: ClassVar[dict[str, StockEntry]] = {
        "pineapple": StockEntry(unit_price=8.00),
        "durian": StockEntry(unit_price=12.00),
        "lychee": StockEntry(unit_price=6.00),
        "mangosteen": StockEntry(unit_price=10.00),
        "rambutan": StockEntry(unit_price=7.00),
        "dragon_fruit": StockEntry(unit_price=5.50),
    }


# ---------- registration helper ----------


ALL_SHOP_CLASSES: tuple[type[FruitShopToolBase], ...] = (
    AppleOrchard,
    CitrusGrove,
    TropicalParadise,
    BerryBasket,
    StoneFruitStand,
    GlobalImports,
)


def register_all_shops(registry: ToolRegistry) -> None:
    """Register all six fruit shops with the given :class:`ToolRegistry`."""
    for shop_cls in ALL_SHOP_CLASSES:
        registry.register(shop_cls())
