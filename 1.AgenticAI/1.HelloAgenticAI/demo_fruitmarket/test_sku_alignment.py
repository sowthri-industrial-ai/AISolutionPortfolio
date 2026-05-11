"""Cross-cutting regression tests that pin the SKU vocabulary used by
the planner LLM and the shop tools to the same set.

Surfaced 2026-05-10 in live UI testing: the agent reported "all berries
out of stock" because the planner emitted singular SKUs (per
``planner.md``'s "Singular form" rule) but BerryBasket's INVENTORY used
plural keys (``blueberries``, etc.). The four shop SKUs were renamed to
singular in the same commit; these tests prevent the same drift from
ever happening again — in either direction.

Three guarantees enforced here:

1. Every shop INVENTORY key follows the singular convention from
   ``planner.md`` (no bare-trailing-s SKUs unless explicitly allowlisted).
2. Every backtick'd SKU literal in ``planner.md`` resolves to a real
   shop INVENTORY key — the planner LLM can't be told about a SKU that
   doesn't exist.
3. Every variant base (any prefix shared by two or more SKUs) has at
   least one ``base_<variant>`` example in ``planner.md`` so the LLM
   knows to emit variants rather than the base alone.
"""

from __future__ import annotations

import re

from demo_fruitmarket.prompts import load_prompt
from demo_fruitmarket.shops import ALL_SHOP_CLASSES

# ---------- allowlists / known non-SKUs ----------


# Allowlist of SKUs that legitimately end in 's' but ARE singular (e.g.
# 'citrus' if a future shop carried a generic citrus mix).
#
# **How to add a new entry:** if a shop genuinely needs an SKU whose
# singular English form ends in 's' (e.g. "molasses", "watercress"),
# add the SKU here. Otherwise, prefer renaming the SKU to a non-s-
# ending form. Today this is empty — every shop SKU follows the simple
# singular-no-trailing-s rule.
PLURAL_LIKE_SINGULARS: frozenset[str] = frozenset()


# Backtick'd identifiers in `planner.md` that AREN'T SKUs:
# - Pydantic field names (``items``, ``budget_usd``, ``preferences``,
#   ``reasoning``)
# - The schema class name (``FruitMarketPlan``)
# - Preference tags (``local``, ``organic``, ``tropical``, ``breakfast``,
#   ``seasonal``)
# - Anti-examples that planner.md explicitly tells the LLM NOT to emit
#   (``pineapples`` — used in "singular form: pineapple not pineapples")
_NON_SKU_BACKTICKS: frozenset[str] = frozenset(
    {
        "items",
        "budget_usd",
        "preferences",
        "reasoning",
        "FruitMarketPlan",
        "local",
        "organic",
        "tropical",
        "breakfast",
        "seasonal",
        "pineapples",  # planner.md anti-example
        "blueberries",  # planner.md anti-example
    }
)


# Backtick'd snake_case literals in markdown — anything from
# `^[a-z][a-z0-9_]*$` between backticks. The classifier filter
# (`_NON_SKU_BACKTICKS`) trims the false positives.
_BACKTICK_LITERAL = re.compile(r"`([a-z][a-z0-9_]*)`")


# ---------- helpers ----------


def _all_inventory_skus() -> set[str]:
    return {sku for cls in ALL_SHOP_CLASSES for sku in cls.INVENTORY}


def _planner_md_sku_candidates() -> set[str]:
    """Backtick'd identifiers in planner.md, minus known non-SKUs."""
    text = load_prompt("planner")
    return set(_BACKTICK_LITERAL.findall(text)) - _NON_SKU_BACKTICKS


# ---------- 1. singular convention ----------


# TODO: heuristic — flags any SKU ending in a bare 's' (and not 'ss').
# Catches the common plural-form mistake (`blueberries`, `apples`). If
# you ever need a SKU whose singular English form genuinely ends in 's'
# (e.g. ``citrus`` for a generic citrus mix), add it to the
# PLURAL_LIKE_SINGULARS allowlist at the top of this module — don't
# weaken the heuristic. The allowlist documents the exception in one
# place and keeps this test honest.
def test_canonical_sku_list_is_singular_or_variant_suffixed() -> None:
    """Shop SKUs follow the singular convention from planner.md."""
    all_skus = _all_inventory_skus()
    plural_offenders = sorted(
        sku
        for sku in all_skus
        if sku.endswith("s") and not sku.endswith("ss") and sku not in PLURAL_LIKE_SINGULARS
    )
    assert plural_offenders == [], (
        f"plural SKUs violate singular convention: {plural_offenders}. "
        "Either rename to singular OR (if the singular form genuinely ends "
        "in 's') add to PLURAL_LIKE_SINGULARS in this file."
    )


# ---------- 2. planner.md SKUs exist in some shop ----------


def test_planner_md_example_skus_appear_in_some_shop_inventory() -> None:
    """SKU literals in planner.md must resolve to a real shop SKU.

    If you add a new SKU example to planner.md, you must also have a shop
    that carries it — otherwise the LLM happily emits an unstockable SKU.
    """
    all_inventory_skus = _all_inventory_skus()
    candidates = _planner_md_sku_candidates()
    missing = sorted(candidates - all_inventory_skus)
    assert not missing, (
        f"planner.md mentions SKUs not in any shop inventory: {missing}. "
        "Either fix the planner.md example OR add the SKU to a shop "
        "INVENTORY. (If the literal isn't a SKU at all — e.g. a new "
        "Pydantic field name — add it to _NON_SKU_BACKTICKS in this file.)"
    )


# ---------- 3. variant bases documented in planner.md ----------


def test_every_variant_base_has_an_example_in_planner_md() -> None:
    """If any SKU base is shared by two or more SKUs (i.e. it has variants),
    planner.md must show at least one ``base_<variant>`` example so the
    LLM emits the variant rather than the base alone.

    Catches a class of latent bug: planner emits ``pear`` (base) when the
    shop has only ``pear_bartlett`` / ``pear_anjou`` (variants), giving
    out_of_stock with no recourse.
    """
    all_skus = _all_inventory_skus()
    bases_to_skus: dict[str, set[str]] = {}
    for sku in all_skus:
        if "_" not in sku:
            continue
        base = sku.split("_", 1)[0]
        bases_to_skus.setdefault(base, set()).add(sku)

    variant_bases = sorted(base for base, skus in bases_to_skus.items() if len(skus) >= 2)

    planner_text = load_prompt("planner")
    missing = []
    for base in variant_bases:
        # Look for a backtick'd `base_<variant>` literal in planner.md
        if not re.search(rf"`{re.escape(base)}_[a-z0-9_]+`", planner_text):
            missing.append(base)

    assert not missing, (
        f"planner.md doesn't show variant examples for: {missing}. "
        "Add at least one `<base>_<variant>` example so the LLM emits "
        "variants. (Latent bug: without an example, the LLM may emit "
        "the bare base which no shop will recognise.)"
    )


# ---------- bonus: berry-fix sanity ----------


def test_berry_basket_uses_singular_sku_keys() -> None:
    """Direct sanity check on the specific bug that motivated this file.

    BerryBasket's INVENTORY must use singular SKU keys (``blueberry``,
    ``raspberry``, ``blackberry``, ``strawberry``) so the planner LLM,
    which follows planner.md's singular rule, finds them on lookup.
    """
    from demo_fruitmarket.shops import BerryBasket

    assert set(BerryBasket.INVENTORY) == {
        "blueberry",
        "raspberry",
        "blackberry",
        "strawberry",
    }
