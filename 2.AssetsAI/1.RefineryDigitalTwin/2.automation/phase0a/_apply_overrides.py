#!/usr/bin/env python3
"""Apply architect overrides to phase0a artifacts.

Three overrides:
  1. Therminol VP1 Storage Tank → thermal_oil (and its 61 tags)
  2. Reboiler Duty energy stream → petroleum
  3. perturbable: false on non-numeric setpoint entries (bounds_kind=='non-numeric')

Patches in place. Refuse-if-exists doesn't apply — we're updating finalized
artifacts per architect decision, not re-running the probe.
"""
import json
import sys
from pathlib import Path

OUT_DIR = Path(
    "/Users/sowthrisomasundaram/Documents/AISolutionPortfolio/"
    "2.AssetsAI/1.RefineryDigitalTwin/3.probes/phase0a"
)

UNIT_OP_OVERRIDE = {"Therminol VP1 Storage Tank": "thermal_oil"}
ENERGY_STREAM_OVERRIDE = {"Reboiler Duty": "petroleum"}


def load(name):
    with open(OUT_DIR / name) as f:
        return json.load(f)


def save(name, data):
    with open(OUT_DIR / name, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  wrote {name} ({(OUT_DIR / name).stat().st_size} bytes)")


def main():
    inventory = load("phase0a_inventory.json")
    tag_dict = load("phase0a_tag_dictionary.json")
    setpoint_dict = load("phase0a_setpoint_dictionary.json")

    # --- Override 1: Storage Tank → thermal_oil ---
    tank_changes = 0
    for o in inventory["objects"]:
        if o["tag"] in UNIT_OP_OVERRIDE:
            old = o["subsystem"]
            o["subsystem"] = UNIT_OP_OVERRIDE[o["tag"]]
            tank_changes += 1
            print(f"  inventory: {o['tag']!r} subsystem {old!r} → {o['subsystem']!r}")

    tag_tank_changes = 0
    for t in tag_dict:
        if t["owner_tag"] in UNIT_OP_OVERRIDE:
            t["subsystem"] = UNIT_OP_OVERRIDE[t["owner_tag"]]
            tag_tank_changes += 1
    print(f"  tag_dictionary: {tag_tank_changes} Storage Tank tags reassigned to thermal_oil")

    setpoint_tank_changes = 0
    for s in setpoint_dict:
        if s["owner_tag"] in UNIT_OP_OVERRIDE:
            s["subsystem"] = UNIT_OP_OVERRIDE[s["owner_tag"]]
            setpoint_tank_changes += 1
    print(f"  setpoint_dictionary: {setpoint_tank_changes} Storage Tank setpoints reassigned")

    # --- Override 2: Reboiler Duty energy stream → petroleum ---
    es_changes = 0
    for o in inventory["objects"]:
        if o["category"] == "energy_stream" and o["tag"] in ENERGY_STREAM_OVERRIDE:
            old = o["subsystem"]
            o["subsystem"] = ENERGY_STREAM_OVERRIDE[o["tag"]]
            es_changes += 1
            print(f"  inventory: energy stream {o['tag']!r} subsystem {old!r} → {o['subsystem']!r}")

    tag_es_changes = 0
    for t in tag_dict:
        if t["owner_type"] == "EnergyStream" and t["owner_tag"] in ENERGY_STREAM_OVERRIDE:
            t["subsystem"] = ENERGY_STREAM_OVERRIDE[t["owner_tag"]]
            tag_es_changes += 1
    print(f"  tag_dictionary: {tag_es_changes} Reboiler Duty energy tags reassigned to petroleum")

    # --- Override 3: perturbable flag ---
    # Architect rule: "non-numeric setpoints (calculation-mode toggles, enums,
    # bools) → hold from perturbation harness; perturbable: false."
    # Detection covers:
    #   - bool current_value (Python bool is also int — check bool first)
    #   - None current_value (no value to perturb)
    #   - Property names with calc-mode semantics:
    #     CalcMode, DebugMode, LegacyMode, FixOnDeltaP, UseTemperatureEstimates,
    #     Active, Enabled, Visible
    MODE_NAMES = (
        "CalcMode", "DebugMode", "LegacyMode", "FixOnDeltaP",
        "UseTemperatureEstimates", "Active", "Enabled", "Visible",
        "DynamicsOnly", "OverrideCalculationRoutine", "StoreDetailedDebugReport",
        "MobileCompatible", "IsAdjustAttached", "IsSpecAttached", "IsSource", "IsSink",
        "CalculateTargetObject", "SupportsDynamicMode",
    )
    perturbable_changes = 0
    for s in setpoint_dict:
        cv = s.get("current_value")
        name = s.get("property_key", "")
        is_bool = isinstance(cv, bool)
        is_none = cv is None
        is_mode_name = any(m in name for m in MODE_NAMES)
        if is_bool or is_none or is_mode_name:
            s["perturbable"] = False
            perturbable_changes += 1
            # Also clear bounds for these — they're not meaningful
            if is_bool or is_mode_name:
                s["bounds"] = None
                s["bounds_kind"] = "non-perturbable"
        else:
            s["perturbable"] = True
    print(f"  setpoint_dictionary: {perturbable_changes} non-perturbable setpoints marked (bool/None/mode-name)")

    # --- Add architect-override note to inventory meta ---
    inventory["meta"]["architect_overrides_applied"] = {
        "unit_op_subsystem": dict(UNIT_OP_OVERRIDE),
        "energy_stream_subsystem": dict(ENERGY_STREAM_OVERRIDE),
        "perturbable_false_count": perturbable_changes,
        "rule_unit_op": "topology wins over property-package metadata when they disagree",
        "rule_energy_stream": "energy streams at subsystem hand-off classified by name/convention, not pure trace",
    }

    # --- Persist ---
    save("phase0a_inventory.json", inventory)
    save("phase0a_tag_dictionary.json", tag_dict)
    save("phase0a_setpoint_dictionary.json", setpoint_dict)

    # --- Sanity counts ---
    petr_tags = sum(1 for t in tag_dict if t.get("subsystem") == "petroleum")
    thoil_tags = sum(1 for t in tag_dict if t.get("subsystem") == "thermal_oil")
    other_tags = len(tag_dict) - petr_tags - thoil_tags
    print()
    print(f"Post-override tag breakdown:")
    print(f"  petroleum:    {petr_tags}")
    print(f"  thermal_oil:  {thoil_tags}")
    print(f"  other:        {other_tags}")
    print(f"  total:        {len(tag_dict)}")

    # Verify Storage Tank tags now in thermal_oil
    tank_tags_in_thermal = sum(1 for t in tag_dict
                                if t["owner_tag"] == "Therminol VP1 Storage Tank"
                                and t["subsystem"] == "thermal_oil")
    print(f"  Storage Tank tags in thermal_oil: {tank_tags_in_thermal}")

    # Verify Reboiler Duty energy tag now in petroleum
    rd_tags_in_petr = sum(1 for t in tag_dict
                           if t["owner_tag"] == "Reboiler Duty"
                           and t["owner_type"] == "EnergyStream"
                           and t["subsystem"] == "petroleum")
    print(f"  Reboiler Duty energy tags in petroleum: {rd_tags_in_petr}")

    print("\nDONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
