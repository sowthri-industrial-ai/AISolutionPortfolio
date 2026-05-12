#!/usr/bin/env python3
"""Stage 4 — OPC-UA node hierarchy builder.

Pure transformation: tag_dict entries → list of node specs that the OPC-UA
server (opcua_server.py) creates as folders + Variable nodes.

No asyncua dependency. Standalone, testable. Run directly to see the tree's
shape against the committed tag dictionary:

    arch -x86_64 ../.venv-x86/bin/python node_hierarchy.py
    arch -x86_64 ../.venv-x86/bin/python node_hierarchy.py /path/to/tag_dict.json

Hierarchy (briefing-aligned):

    Refinery/
    ├── PetroleumSide/
    │   ├── MaterialStreams/<owner>/<phase>/<prop>  (compositions nest deeper)
    │   ├── EnergyStreams/<owner>/<prop>
    │   └── Columns/<owner>/STAGE_<n>/<prop>  (stage tags nest one level deeper;
    │                                          global column tags sit under <owner>/)
    └── ThermalOilLoop/
        ├── MaterialStreams/<owner>/<phase>/<prop>
        ├── EnergyStreams/<owner>/<prop>
        └── Equipment/<owner>/<prop>   (Heater + Pump + Tank + Recycle, flat)
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

DEFAULT_TAG_DICT = (
    "/Users/sowthrisomasundaram/Documents/AISolutionPortfolio/"
    "2.AssetsAI/1.RefineryDigitalTwin/3.probes/phase0a/phase0a_tag_dictionary.json"
)

# Subsystem → top-level branch under Refinery/.
SUBSYSTEM_FOLDER = {
    "petroleum": "PetroleumSide",
    "thermal_oil": "ThermalOilLoop",
}

# owner_type → 2nd-level category folder.
OWNER_TYPE_FOLDER = {
    "MaterialStream": "MaterialStreams",
    "EnergyStream": "EnergyStreams",
    "DistillationColumn": "Columns",
    "Heater": "Equipment",
    "Pump": "Equipment",
    "Tank": "Equipment",
    "Recycle": "Equipment",
}

# Phase values that translate to a folder layer under the owner.
PHASE_FOLDERS = {"OVERALL", "VAPOR", "LIQUID"}

STAGE_RE = re.compile(r"\.STAGE_(\d+)\.")


@dataclass(frozen=True)
class NodeSpec:
    """One Variable node in the OPC-UA tree + the folder path to it."""

    folder_path: tuple[str, ...]  # e.g., ("PetroleumSide", "MaterialStreams", "MS-OIL", "OVERALL")
    leaf_name: str  # e.g., "PROP_MS_0"
    ua_type: str  # "Double" | "Boolean" | "String" | "Int32"
    tag_id: str  # source tag_id (used by the server to look up values in each snapshot)


def _owner_browse_from_tag_id(tag_id: str) -> str:
    """First segment of tag_id (e.g., 'MS-OIL' from 'MS-OIL.OVERALL.PROP_MS_0').
    Tag IDs are already Phase-0a-normalized (alphanumeric + '-' separator)."""
    return tag_id.split(".", 1)[0]


def _ua_type_from_value(v: Any) -> str:
    """Map a Python value to an OPC-UA variant type name.

    Pythonnet / DWSIM values from Phase 0a probe-time. Note: isinstance(bool, int)
    is True in Python, so check bool first.

    Python ints map to Int64 (not Int32): the asyncua Variant infers Int64 by
    default when packing Python int values (Python ints can be arbitrary size),
    so the node's declared type must match or writes fail with
    BadTypeMismatch. Bug 2 from A2 smoke (2026-05-11).
    """
    if isinstance(v, bool):
        return "Boolean"
    if isinstance(v, int):
        return "Int64"
    if isinstance(v, float):
        return "Double"
    if isinstance(v, str):
        return "String"
    # None or other → default to Double (most common runtime type for this substrate)
    return "Double"


def derive_node_path(entry: dict) -> Optional[tuple[tuple[str, ...], str, str]]:
    """Return (folder_path, leaf_name, ua_type) for a tag dict entry, or None
    if the entry can't be placed in the hierarchy (missing fields, unknown
    subsystem/owner_type)."""
    subsystem = entry.get("subsystem")
    owner_type = entry.get("owner_type")
    property_key = entry.get("property_key")
    tag_id = entry.get("tag_id")
    phase = entry.get("phase")
    current_value = entry.get("current_value")

    if not (subsystem and owner_type and property_key and tag_id):
        return None

    top = SUBSYSTEM_FOLDER.get(subsystem)
    category = OWNER_TYPE_FOLDER.get(owner_type)
    if top is None or category is None:
        return None

    folders: list[str] = [top, category, _owner_browse_from_tag_id(tag_id)]

    # Column stage tags get one more level (STAGE_N).
    m = STAGE_RE.search(tag_id)
    if m:
        folders.append(f"STAGE_{m.group(1)}")

    # Multi-phase material streams get a phase folder.
    if phase in PHASE_FOLDERS:
        folders.append(phase)

    # Compositions (MoleFraction.<C>, MassFraction.<C>, LiqMoleFraction.<C>) get a
    # composition-type folder; the leaf is the compound name.
    if "." in property_key:
        head, tail = property_key.split(".", 1)
        folders.append(head)
        leaf = tail
    else:
        leaf = property_key

    ua_type = _ua_type_from_value(current_value)
    return (tuple(folders), leaf, ua_type)


def build_node_specs(tag_dict_entries: list[dict]) -> list[NodeSpec]:
    """Transform tag dict entries into NodeSpec list. Entries that can't be
    placed (missing/unknown subsystem or owner_type) are skipped silently —
    counts can be derived by comparing input vs output length."""
    out: list[NodeSpec] = []
    for entry in tag_dict_entries:
        derived = derive_node_path(entry)
        if derived is None:
            continue
        folders, leaf, ua_type = derived
        out.append(
            NodeSpec(folder_path=folders, leaf_name=leaf, ua_type=ua_type, tag_id=entry["tag_id"])
        )
    return out


# ----- Self-check entry point (no asyncua needed) -----


def _summarize(specs: list[NodeSpec], total_input: int) -> None:
    print(f"loaded {total_input} tag dict entries → {len(specs)} node specs")
    if total_input != len(specs):
        print(f"  ({total_input - len(specs)} entries skipped — missing subsystem/owner_type)")
    print()

    top_counts = Counter(s.folder_path[0] if s.folder_path else "?" for s in specs)
    print("Top-level branch distribution:")
    for top, n in top_counts.most_common():
        print(f"  {top:20s} {n}")

    print()
    cat_counts = Counter(
        f"{s.folder_path[0]}/{s.folder_path[1]}" if len(s.folder_path) >= 2 else "?"
        for s in specs
    )
    print("Subsystem/category distribution:")
    for cat, n in cat_counts.most_common():
        print(f"  {cat:40s} {n}")

    print()
    type_counts = Counter(s.ua_type for s in specs)
    print("ua_type distribution:")
    for t, n in type_counts.most_common():
        print(f"  {t:10s} {n}")

    print()
    depths = Counter(len(s.folder_path) for s in specs)
    print("Folder-depth distribution (lower = shallower; max should be ~5):")
    for depth, n in sorted(depths.items()):
        print(f"  depth {depth}: {n}")

    # Sample paths for visual sanity.
    print()
    print("Sample node paths (first 5 per top-level branch):")
    seen: Counter = Counter()
    for s in specs:
        top = s.folder_path[0]
        if seen[top] < 5:
            seen[top] += 1
            print(f"  /{'/'.join(s.folder_path)}/{s.leaf_name}  ({s.ua_type}) ← {s.tag_id}")


if __name__ == "__main__":
    import sys

    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(DEFAULT_TAG_DICT)
    if not path.is_file():
        sys.stderr.write(f"tag dict not found: {path}\n")
        sys.exit(1)
    with open(path) as f:
        entries = json.load(f)
    specs = build_node_specs(entries)
    _summarize(specs, len(entries))
