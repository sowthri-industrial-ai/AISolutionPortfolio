#!/usr/bin/env python3
"""Stage 3 — Ontology loader.

In-process consumer of the F2 data files (docs/ontology/):
  - schema.json            entity type definitions
  - refinery_instance.json 26 entities (23 Phase 0a + 3 aggregators)
  - tag_mapping.json       1550 tag → entity bindings

Stays asyncua-free, FastAPI-free, framework-free — pure Python so the
data can be loaded the same way in any consumer (Stage 3 API, future
agents, scripts). The Stage 3 API wires this into HTTP endpoints in a
separate commit (api.py).

Public surface (per F2 briefing):
    OntologyLoader(schema_path, instance_path, tag_mapping_path)
    .schema                 raw schema dict
    .entities               entity_id → entity dict
    .tag_mapping            raw tag_mapping envelope
    .get_entity(id)         single entity or None
    .get_tag_info(tag_id)   single tag mapping entry or None
    .list_entities_by_type(type_name)
    .get_tags_for_entity(entity_id)
    .get_relationships(entity_id) → {"outbound": [...], "inbound": [...]}
    .resolve_term(term)     ranked list of {entity_id, name, type,
                                            match_type, matched_phrase,
                                            score, tag_ids}

Run directly for a self-check against the committed ontology files:
    arch -x86_64 ../.venv-x86/bin/python ontology.py
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA_PATH = REPO_ROOT / "docs" / "ontology" / "schema.json"
DEFAULT_INSTANCE_PATH = REPO_ROOT / "docs" / "ontology" / "refinery_instance.json"
DEFAULT_TAG_MAPPING_PATH = REPO_ROOT / "docs" / "ontology" / "tag_mapping.json"


class OntologyLoader:
    def __init__(
        self,
        schema_path: Path = DEFAULT_SCHEMA_PATH,
        instance_path: Path = DEFAULT_INSTANCE_PATH,
        tag_mapping_path: Path = DEFAULT_TAG_MAPPING_PATH,
    ):
        self.schema_path = Path(schema_path)
        self.instance_path = Path(instance_path)
        self.tag_mapping_path = Path(tag_mapping_path)

        # Eagerly load all three. Small files; one-shot cost at startup.
        with open(self.schema_path) as f:
            self.schema: dict[str, Any] = json.load(f)
        with open(self.instance_path) as f:
            instance = json.load(f)
        self.entities: dict[str, dict] = instance["entities"]
        with open(self.tag_mapping_path) as f:
            self.tag_mapping: dict[str, Any] = json.load(f)

        # Indices built once at load. O(1) lookup at query time.
        self._tag_index: dict[str, dict] = {
            m["tag_id"]: m for m in self.tag_mapping["mappings"]
        }
        self._entity_to_tags: dict[str, list[str]] = defaultdict(list)
        for m in self.tag_mapping["mappings"]:
            self._entity_to_tags[m["entity_id"]].append(m["tag_id"])

        # Inbound relationship index: target_id → [{type, source}]
        self._inbound: dict[str, list[dict[str, str]]] = defaultdict(list)
        for src_id, e in self.entities.items():
            for rel in e.get("relationships", []) or []:
                self._inbound[rel["target"]].append(
                    {"type": rel["type"], "source": src_id}
                )

        # Alias index: lower-case phrase → set of entity_ids.
        # Indexes: id, name, every entry in aliases[]. Substring matching
        # is done at resolve time by iterating the index keys.
        self._alias_to_entities: dict[str, set[str]] = defaultdict(set)
        for eid, e in self.entities.items():
            self._alias_to_entities[eid.lower()].add(eid)
            name = (e.get("name") or "").strip()
            if name:
                self._alias_to_entities[name.lower()].add(eid)
            for alias in e.get("aliases") or []:
                a = alias.strip().lower()
                if a:
                    self._alias_to_entities[a].add(eid)

    # ---- Single-shot accessors ----

    def get_entity(self, entity_id: str) -> Optional[dict]:
        return self.entities.get(entity_id)

    def get_tag_info(self, tag_id: str) -> Optional[dict]:
        return self._tag_index.get(tag_id)

    def list_entities_by_type(self, type_name: str) -> list[dict]:
        return [e for e in self.entities.values() if e.get("type") == type_name]

    def get_tags_for_entity(self, entity_id: str) -> list[str]:
        return list(self._entity_to_tags.get(entity_id, []))

    def get_relationships(self, entity_id: str) -> dict:
        """Return both directions for one entity.

        outbound: this entity's `relationships[]` (target = other entity)
        inbound:  other entities whose relationships point to this entity
                  (each item: {"type", "source"})
        """
        e = self.entities.get(entity_id)
        outbound = list(e.get("relationships", []) or []) if e else []
        inbound = list(self._inbound.get(entity_id, []))
        return {"outbound": outbound, "inbound": inbound}

    # ---- Natural-language resolution ----

    def resolve_term(self, term: str) -> list[dict]:
        """Map a natural-language term to entities and their tag_ids.

        Two-tier match per Q2 hybrid default:
          1. Exact alias match against the alias index → score 100
          2. Substring fallback: term ⊆ phrase OR phrase ⊆ term → score
             scaled by length proportion (capped at 95 so it never beats
             exact match)

        Returns a list of hits sorted by score desc, deduplicated by
        entity_id (highest-scoring match per entity wins). Each hit:
            {entity_id, name, type, match_type, matched_phrase, score,
             tag_ids[]}
        """
        term_lc = (term or "").strip().lower()
        if not term_lc:
            return []

        # Two-phase: collect (score, entity_id, match_type, phrase),
        # then dedupe by entity_id keeping the highest score.
        candidates: list[tuple[int, str, str, str]] = []

        # 1. Exact match
        if term_lc in self._alias_to_entities:
            for eid in self._alias_to_entities[term_lc]:
                candidates.append((100, eid, "exact", term_lc))

        # 2. Substring fallback
        for phrase, eids in self._alias_to_entities.items():
            if phrase == term_lc:
                continue
            contains = term_lc in phrase
            contained = phrase in term_lc
            if not (contains or contained):
                continue
            # Score: scale by ratio of shorter/longer length. Caps below
            # exact-match score (100).
            shorter = min(len(phrase), len(term_lc))
            longer = max(len(phrase), len(term_lc))
            ratio = shorter / longer if longer else 0
            score = min(int(50 + 45 * ratio), 95)
            for eid in eids:
                candidates.append((score, eid, "substring", phrase))

        # Dedupe by entity_id, keep highest-scoring match per entity.
        best_by_entity: dict[str, tuple[int, str, str]] = {}
        for score, eid, mtype, phrase in candidates:
            current = best_by_entity.get(eid)
            if current is None or score > current[0]:
                best_by_entity[eid] = (score, mtype, phrase)

        # Build response, sorted by score desc then entity_id asc for
        # determinism.
        results: list[dict] = []
        for eid, (score, mtype, phrase) in sorted(
            best_by_entity.items(), key=lambda kv: (-kv[1][0], kv[0])
        ):
            e = self.entities[eid]
            results.append(
                {
                    "entity_id": eid,
                    "name": e.get("name"),
                    "type": e.get("type"),
                    "match_type": mtype,
                    "matched_phrase": phrase,
                    "score": score,
                    "tag_ids": self.get_tags_for_entity(eid),
                }
            )
        return results


# ---- Self-check ----


def _self_check() -> int:
    """Self-check the loader against the committed ontology files. Returns
    process exit code (0 ok, 1 mismatch)."""
    ol = OntologyLoader()
    fail = 0

    def check(label: str, cond: bool, detail: str = "") -> None:
        nonlocal fail
        if cond:
            print(f"  PASS  {label}")
        else:
            fail += 1
            print(f"  FAIL  {label}: {detail}")

    print("=== Load stats ===")
    print(f"  schema types:          {len(ol.schema['entity_types'])}")
    print(f"  entities:              {len(ol.entities)}")
    print(f"  tag mappings:          {ol.tag_mapping['tag_count']}")
    print(f"  alias index keys:      {len(ol._alias_to_entities)}")
    print(f"  inbound rel targets:   {len(ol._inbound)}")

    print()
    print("=== Single-shot accessors ===")
    check("get_entity('COL-DISTILLATION_COLUMN') returns Column",
          ol.get_entity("COL-DISTILLATION_COLUMN") is not None
          and ol.get_entity("COL-DISTILLATION_COLUMN")["type"] == "Column")
    check("get_entity('NONEXISTENT') returns None",
          ol.get_entity("NONEXISTENT") is None)
    check("get_tag_info('ES-CONDENSER_DUTY.EnergyFlow') resolves",
          ol.get_tag_info("ES-CONDENSER_DUTY.EnergyFlow") is not None
          and ol.get_tag_info("ES-CONDENSER_DUTY.EnergyFlow")["entity_id"]
              == "ES-CONDENSER_DUTY")
    check("list_entities_by_type('MaterialStream') → 10",
          len(ol.list_entities_by_type("MaterialStream")) == 10)
    check("list_entities_by_type('EnergyStream') → 5",
          len(ol.list_entities_by_type("EnergyStream")) == 5)
    check("get_tags_for_entity('MS-OIL') → 180 tags (multi-phase)",
          len(ol.get_tags_for_entity("MS-OIL")) == 180)
    check("get_tags_for_entity('REFINERY') → 0 (aggregator)",
          len(ol.get_tags_for_entity("REFINERY")) == 0)

    print()
    print("=== Relationships ===")
    col_rels = ol.get_relationships("COL-DISTILLATION_COLUMN")
    check("column outbound: RECEIVES_FEED_FROM + 4 PRODUCES + 2 duty",
          len(col_rels["outbound"]) == 7)
    # Inbound is the SUM of all relationships pointing at the column.
    # Data encodes both directions for query convenience: the 4 products
    # and the condenser-duty stream all declare FROM → COL on top of the
    # column's own outbound PRODUCES / REJECTS_DUTY edges. Plus the feed
    # stream's TO → COL, the reboiler duty's TO → COL, and the subsystem's
    # CONTAINS → COL. Total: 8 inbound relationships, 8 unique sources.
    inbound_sources = {r["source"] for r in col_rels["inbound"]}
    expected_sources = {
        "SS-PETROLEUM_SIDE",
        "MS-OIL",
        "MS-LIGHT_PRODUCT",
        "MS-LIGHT_INTERMEDIATE_PRODUCT",
        "MS-INTERMEDIATE_PRODUCT",
        "MS-HEAVY_PRODUCT",
        "ES-CONDENSER_DUTY",
        "ES-REBOILER_DUTY",
    }
    check("column inbound: all 8 reverse-direction sources resolve",
          inbound_sources == expected_sources,
          f"got {inbound_sources}")
    ms_oil_rels = ol.get_relationships("MS-OIL")
    check("MS-OIL inbound: CONTAINS from SS-PETROLEUM_SIDE + "
          "RECEIVES_FEED_FROM from COL-DISTILLATION_COLUMN",
          len(ms_oil_rels["inbound"]) == 2)

    print()
    print("=== Resolve term ===")
    cd = ol.resolve_term("condenser duty")
    check("resolve('condenser duty') top hit is ES-CONDENSER_DUTY",
          len(cd) >= 1 and cd[0]["entity_id"] == "ES-CONDENSER_DUTY")
    check("resolve('condenser duty') top hit tag_ids includes EnergyFlow",
          len(cd) >= 1 and "ES-CONDENSER_DUTY.EnergyFlow" in cd[0]["tag_ids"])
    check("resolve('condenser duty') top hit score == 100 (exact)",
          len(cd) >= 1 and cd[0]["score"] == 100)
    col = ol.resolve_term("the column")
    check("resolve('the column') top hit is COL-DISTILLATION_COLUMN",
          len(col) >= 1 and col[0]["entity_id"] == "COL-DISTILLATION_COLUMN")
    oil = ol.resolve_term("oil")
    check("resolve('oil') matches MS-OIL (substring or exact)",
          any(h["entity_id"] == "MS-OIL" for h in oil))
    therm = ol.resolve_term("thermal oil")
    check("resolve('thermal oil') matches multiple entities (loop, pump, heater, …)",
          len(therm) >= 2)
    empty = ol.resolve_term("")
    check("resolve('') → empty list", empty == [])
    bogus = ol.resolve_term("zxqvb_does_not_exist")
    check("resolve('zxqvb_does_not_exist') → empty list", bogus == [])

    print()
    if fail:
        print(f"FAILED: {fail} check(s)")
        return 1
    print("self-check OK")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(_self_check())
