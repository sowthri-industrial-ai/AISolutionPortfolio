"""Pydantic schemas for the fruit-shop tools.

:class:`ShopRequest` / :class:`ShopResponse` are the typed I/O contract
every shop tool exposes to the agent. Held as a separate module so
subclasses (and tests) can import the schemas without pulling the full
inventory data in :mod:`demo_fruitmarket.shops`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class BasketItem(BaseModel):
    """One line in a shop request — what the agent wants to buy."""

    model_config = ConfigDict(frozen=True)

    sku: str = Field(min_length=1, max_length=64)
    quantity: int = Field(ge=1, le=100)


class ShopRequest(BaseModel):
    """The agent's basket of items, sent to a shop tool's ``call()``."""

    basket: list[BasketItem] = Field(min_length=1, max_length=20)


class PurchasedLine(BaseModel):
    """One line of what was actually purchased at a shop.

    ``quantity`` may be lower than the requested quantity (rationed item).
    """

    model_config = ConfigDict(frozen=True)

    sku: str = Field(min_length=1)
    quantity: int = Field(ge=0)
    unit_price: float = Field(ge=0)
    line_total: float = Field(ge=0)


class ShopResponse(BaseModel):
    """The shop's response to a :class:`ShopRequest`.

    * ``purchased`` — items the shop sold (possibly partial quantities).
    * ``out_of_stock`` — SKUs the shop doesn't stock or is currently out of.
    * ``rationed`` — SKUs partially fulfilled (the agent should consider
      sourcing the remainder elsewhere).
    """

    shop_name: str = Field(min_length=1)
    purchased: list[PurchasedLine] = Field(default_factory=list)
    out_of_stock: list[str] = Field(default_factory=list)
    rationed: list[str] = Field(default_factory=list)
    total_price: float = Field(ge=0, default=0.0)
    notes: str = ""
