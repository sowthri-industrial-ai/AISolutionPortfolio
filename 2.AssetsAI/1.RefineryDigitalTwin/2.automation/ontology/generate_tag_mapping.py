#!/usr/bin/env python3
"""Generate docs/ontology/tag_mapping.json from the Phase 0a tag dictionary.

Per F2 design (D2): project the tag dict's existing `description` and
`unit_si` fields straight through. No re-derivation. Entity_id and
property path are derived from tag_id via regex — deterministic and
re-runnable if the tag dict updates.

Mapping shape (per tag):
    {
      "tag_id":     "<source tag_id>",
      "entity_id":  "<ontology entity ID — matches refinery_instance.json>",
      "property":   "<canonical property path within the entity>",
      "description": "<tag dict description, projected as-is>",
      "unit":       "<tag dict unit_si, projected as-is>",
      "category":   "<tag dict category, projected as-is>"
    }

Property path normalization:
    MS-OIL.OVERALL.PROP_MS_0           → entity=MS-OIL, property=OVERALL.PROP_MS_0
    MS-OIL.MoleFraction.PSE_3165_2     → entity=MS-OIL, property=MoleFraction.PSE_3165_2
    ES-CONDENSER_DUTY.EnergyFlow       → entity=ES-CONDENSER_DUTY, property=EnergyFlow
    COL-DISTILLATION_COLUMN.STAGE_3.T_K → entity=COL-DISTILLATION_COLUMN, property=stages[3].T_K
    COL-DISTILLATION_COLUMN.RefluxRatio → entity=COL-DISTILLATION_COLUMN, property=RefluxRatio

Stage tags get the JSONPath-flavoured `stages[N].<leaf>` form so the
loader can resolve them to the nested Stage inside the Column entity.

Run:
    arch -x86_64 ../.venv-x86/bin/python generate_tag_mapping.py
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TAG_DICT_PATH = REPO_ROOT / "3.probes" / "phase0a" / "phase0a_tag_dictionary.json"
OUTPUT_PATH = REPO_ROOT / "docs" / "ontology" / "tag_mapping.json"

# tag_id always has an owner prefix as the first dot-segment, e.g.,
# MS-OIL.OVERALL.PROP_MS_0 → prefix MS-OIL. The prefix matches an
# entity ID in refinery_instance.json. Phase 0a Q1 normalization rule
# guarantees alphanumeric + dashes + underscores only.
ENTITY_PREFIX_RE = re.compile(r"^([A-Z]+(?:-[A-Z0-9_]+)?)\.")

# Stage tag pattern: COL-X.STAGE_N.<leaf>
STAGE_RE = re.compile(r"^([A-Z]+(?:-[A-Z0-9_]+)?)\.STAGE_(\d+)\.(.+)$")


def derive_entity_and_property(tag_id: str) -> tuple[str | None, str | None]:
    """Parse tag_id into (entity_id, property_path)."""
    m = STAGE_RE.match(tag_id)
    if m:
        entity_id = m.group(1)
        stage_idx = int(m.group(2))
        leaf = m.group(3)
        return entity_id, f"stages[{stage_idx}].{leaf}"
    m = ENTITY_PREFIX_RE.match(tag_id)
    if m:
        entity_id = m.group(1)
        property_path = tag_id[len(entity_id) + 1:]  # everything after "<prefix>."
        return entity_id, property_path
    return None, None


def main() -> int:
    if not TAG_DICT_PATH.is_file():
        sys.stderr.write(f"tag dict not found: {TAG_DICT_PATH}\n")
        return 1
    with open(TAG_DICT_PATH) as f:
        tags = json.load(f)

    out: list[dict] = []
    skipped: list[str] = []
    for t in tags:
        tag_id = t["tag_id"]
        entity_id, prop = derive_entity_and_property(tag_id)
        if entity_id is None:
            skipped.append(tag_id)
            continue
        out.append({
            "tag_id": tag_id,
            "entity_id": entity_id,
            "property": prop,
            "description": t.get("description") or "",
            "unit": t.get("unit_si") or "",
            "category": t.get("category") or "",
        })

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    envelope = {
        "version": "0.1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator": "2.automation/ontology/generate_tag_mapping.py",
        "source_tag_dict": str(TAG_DICT_PATH.relative_to(REPO_ROOT)),
        "tag_count": len(out),
        "mappings": out,
    }
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(envelope, f, indent=2, ensure_ascii=False)

    print(f"wrote {OUTPUT_PATH} ({OUTPUT_PATH.stat().st_size} bytes)")
    print(f"  total tags processed: {len(tags)}")
    print(f"  entries emitted:      {len(out)}")
    print(f"  entries skipped:      {len(skipped)}")
    if skipped:
        print(f"  first 5 skipped tag_ids: {skipped[:5]}")

    by_entity = Counter(e["entity_id"] for e in out)
    print(f"  unique entities referenced: {len(by_entity)}")
    print(f"  top 10 by tag count:")
    for ent, n in by_entity.most_common(10):
        print(f"    {ent:42s} {n}")

    by_category = Counter(e["category"] for e in out)
    print(f"  by category:")
    for cat, n in by_category.most_common():
        print(f"    {cat:25s} {n}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
