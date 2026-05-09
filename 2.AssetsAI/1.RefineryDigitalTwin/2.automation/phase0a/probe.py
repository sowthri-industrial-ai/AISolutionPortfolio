#!/usr/bin/env python3
"""
Phase 0a substrate inventory probe.

Inventories every readable property and writable spec in the locked substrate
flowsheet (Petroleum Distillation with Reboiler Heating Fluid.dwxmz). Emits
six artifacts plus a pre-solve baseline.

Run pattern (from 2.automation/phase0a/):
    arch -x86_64 ../.venv-x86/bin/python probe.py

KB rules honored: refuse-if-exists, save-before-solve, 2-arg MessageListener,
verify-after-write, probe-before-assuming, 3-attempt cap (single run here).
"""

import argparse
import json
import math
import os
import re
import shutil
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path


# ============================================================================
# Constants
# ============================================================================

DEFAULT_SUBSTRATE = (
    "/Applications/DWSIM.app/Contents/MonoBundle/samples/"
    "Petroleum Distillation with Reboiler Heating Fluid.dwxmz"
)

DEFAULT_OUTPUT_DIR = (
    "/Users/sowthrisomasundaram/Documents/AISolutionPortfolio/"
    "2.AssetsAI/1.RefineryDigitalTwin/3.probes/phase0a/"
)

DWSIM_DLLS = [
    "/Applications/DWSIM.app/Contents/MonoBundle/DWSIM.Automation.dll",
    "/Applications/DWSIM.app/Contents/MonoBundle/DWSIM.Interfaces.dll",
    "/Applications/DWSIM.app/Contents/MonoBundle/DWSIM.Thermodynamics.dll",
]

OUTPUT_FILES = [
    "phase0a_substrate_pre_solve.dwxmz",
    "phase0a_probe.log",
    "phase0a_inventory.json",
    "phase0a_tag_dictionary.json",
    "phase0a_setpoint_dictionary.json",
    "phase0a_constraint_dictionary.json",
    "phase0a_findings.md",
]

PROP_MS_MAX_INDEX = 50  # Q3: cap, stop at first raise OR at 50

# Setpoint default bounds (Q4)
PCT_DEFAULT_BOUNDS = 0.20
TEMP_BOUND_DELTA_K = 20.0
MOLE_FRAC_BOUNDS = (0.01, 0.99)
EFFICIENCY_BOUNDS = (0.5, 1.0)

BUG6_LIGHT_PRODUCT_MIN_COMPS = 10
BUG6_MOLE_FRAC_THRESHOLD = 0.01

# Best-effort PROP_MS_X → phase.Properties field mapping.
# Used for emitting per-phase tags on multi-phase streams (Oil) so VAPOR/LIQUID
# tag IDs can mirror the OVERALL PROP_MS_X namespace per the briefing example
# (MS-OIL.VAPOR.PROP_MS_2). If the field is absent on phase.Properties for a
# given key, that per-phase tag is silently skipped (still emitted under OVERALL).
PROP_MS_PHASE_FIELD = {
    "PROP_MS_0": "temperature",
    "PROP_MS_1": "pressure",
    "PROP_MS_2": "massflow",
    "PROP_MS_3": "molarflow",
    "PROP_MS_4": "volumetric_flow",
    "PROP_MS_5": "density",
    "PROP_MS_6": "enthalpy",
    "PROP_MS_7": "entropy",
    "PROP_MS_8": "molar_enthalpy",
    "PROP_MS_9": "molar_entropy",
    "PROP_MS_10": "molecularWeight",
}

# Energy stream name → subsystem fallback (Q2). Resolved AFTER topology trace.
ENERGY_NAME_FALLBACK = [
    ("Reboiler Duty (2)", "thermal_oil"),
    ("Heating Duty", "thermal_oil"),
    ("ESTR-017", "thermal_oil"),
    ("Condenser Duty", "petroleum"),
    ("Reboiler Duty", "petroleum"),
]


# ============================================================================
# Tag ID normalization (Q1)
# ============================================================================

_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")
_RUN_UNDER = re.compile(r"_+")


def normalize_tag(s):
    """Q1: non-alphanumeric → '_', collapse runs, strip ends, uppercase."""
    s = s or ""
    out = _NON_ALNUM.sub("_", s)
    out = _RUN_UNDER.sub("_", out).strip("_").upper()
    return out


def make_tag_id(prefix, owner_tag, *parts):
    """Build canonical tag_id: <Prefix>-<NormalizedOwnerTag>[.<part>]*"""
    base = f"{prefix}-{normalize_tag(owner_tag)}"
    if parts:
        return base + "." + ".".join(str(p) for p in parts)
    return base


# ============================================================================
# Logger
# ============================================================================

class Logger:
    def __init__(self, log_path):
        self.fp = open(str(log_path), "a", encoding="utf-8")

    def log(self, msg, level="INFO"):
        ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        line = f"[{ts}] [{level}] {msg}"
        print(line, flush=True)
        self.fp.write(line + "\n")
        self.fp.flush()

    def dwsim_listener(self, msg, level):
        try:
            level_str = str(level)
            msg_str = str(msg)
        except Exception:
            level_str = repr(level)
            msg_str = repr(msg)
        self.log(f"DWSIM> {msg_str}", level=f"DW_{level_str}")

    def close(self):
        try:
            self.fp.flush()
            self.fp.close()
        except Exception:
            pass


# ============================================================================
# JSON-safe coercion
# ============================================================================

def coerce(v):
    """Coerce .NET / Python value to JSON-safe primitive. None on NaN/Inf."""
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int,)):
        return int(v)
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    if isinstance(v, str):
        return v
    # Try float
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError, OverflowError):
        pass
    # Try int
    try:
        return int(v)
    except (TypeError, ValueError):
        pass
    # Fallback to str repr (e.g. enums)
    try:
        return str(v)
    except Exception:
        return None


def write_json(path, data, log):
    with open(str(path), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    log.log(f"Wrote {path} ({path.stat().st_size} bytes)")


# ============================================================================
# Reflection helpers
#
# pythonnet exposes DWSIM SimulationObjects via the ISimulationObject interface,
# which masks concrete-class members (NumberOfStages, PropertyPackage, etc).
# Reflection through `obj.GetType().GetProperty(name).GetValue(obj, None)`
# bypasses the masking. Use these helpers for any DWSIM property/method access.
# ============================================================================

def rget(obj, name, default=None):
    """Read a .NET property by name via reflection. Returns default on failure."""
    if obj is None:
        return default
    try:
        prop = obj.GetType().GetProperty(name)
        if prop is None or not prop.CanRead:
            return default
        return prop.GetValue(obj, None)
    except Exception:
        return default


def rcall(obj, method_name, *args):
    """Invoke a .NET method by name via reflection.

    Raises AttributeError if no overload matches arg count.
    Re-raises target exceptions (wrapped or unwrapped) so callers can
    distinguish "method missing" from "method returned" from "method threw".
    """
    if obj is None:
        raise AttributeError(f"rcall on None ({method_name})")
    methods = [m for m in obj.GetType().GetMethods() if str(m.Name) == method_name]
    for m in methods:
        try:
            params = m.GetParameters()
            n_params = params.Length if hasattr(params, 'Length') else len(list(params))
        except Exception:
            continue
        if n_params == len(args):
            from System import Array, Object
            arr = Array[Object](list(args))
            return m.Invoke(obj, arr)
    raise AttributeError(f"No method {method_name}({len(args)} args) on {obj.GetType().Name}")


# ============================================================================
# Pre-flight
# ============================================================================

def preflight(substrate, out_dir):
    """Refuse-if-exists. No I/O before this clears."""
    if not substrate.is_file():
        sys.stderr.write(f"FATAL: substrate not found: {substrate}\n")
        sys.exit(1)
    if out_dir.exists():
        for fname in OUTPUT_FILES:
            p = out_dir / fname
            if p.exists():
                sys.stderr.write(f"FATAL: refuse-if-exists: {p}\n")
                sys.exit(1)


# ============================================================================
# Object inspection helpers
# ============================================================================

def safe_attr(obj, name, default=None):
    try:
        return getattr(obj, name, default)
    except Exception:
        return default


def get_obj_tag(obj):
    """GraphicObject.Tag (UI display name). GraphicObject IS on the interface."""
    go = getattr(obj, "GraphicObject", None)
    if go is None:
        go = rget(obj, "GraphicObject")
    if go is not None:
        v = getattr(go, "Tag", None) or rget(go, "Tag")
        if v is not None:
            return str(v)
    return ""


def get_obj_type_str(obj):
    """Use .NET runtime concrete class name. Interface is ISimulationObject."""
    try:
        n = str(obj.GetType().Name)
        if n and n != "ISimulationObject":
            return n
    except Exception:
        pass
    # Fallback paths
    try:
        ot = rget(obj, "ObjectType")
        if ot is not None:
            s = str(ot)
            if "." in s:
                s = s.rsplit(".", 1)[-1]
            return s
    except Exception:
        pass
    return type(obj).__name__


def get_internal_name(obj):
    n = rget(obj, "Name")
    if n:
        return str(n)
    go = rget(obj, "GraphicObject")
    if go is not None:
        v = getattr(go, "Name", None) or rget(go, "Name")
        if v:
            return str(v)
    return ""


def is_calculated(obj):
    v = rget(obj, "Calculated", False)
    try:
        return bool(v) if v is not None else False
    except Exception:
        return False


def get_pp_name(obj):
    """Property package name or None. Reflection-only on top-level DWSIM obj."""
    pp = rget(obj, "PropertyPackage")
    if pp is None:
        return None
    # pp is a concrete PropertyPackage object — direct access works on this layer
    for attr in ("ComponentName", "Name", "Tag"):
        v = getattr(pp, attr, None)
        if v:
            return str(v)
    return type(pp).__name__


def subsystem_from_pp_name(pp_name):
    if not pp_name:
        return None
    n = pp_name.lower()
    if "peng" in n or "robinson" in n or n.strip() == "pr":
        return "petroleum"
    if "coolprop" in n or "incompressible" in n:
        return "thermal_oil"
    return None


def subsystem_from_name_fallback(obj_tag):
    if not obj_tag:
        return None
    for pat, sub in ENERGY_NAME_FALLBACK:
        if pat == obj_tag:
            return sub
    if re.match(r"^ESTR[-_]\d+", obj_tag):
        return "thermal_oil"
    if "Heating" in obj_tag:
        return "thermal_oil"
    if "(2)" in obj_tag:
        return "thermal_oil"
    if "Condenser" in obj_tag:
        return "petroleum"
    return None


def classify_object(obj_type_str):
    s = obj_type_str
    if "Material" in s and "Stream" in s:
        return "material_stream"
    if "Energy" in s and "Stream" in s:
        return "energy_stream"
    if "Distillation" in s or s == "DistillationC":
        return "column"
    if "Heater" in s or "Cooler" in s:
        return "heater"
    if "Pump" in s:
        return "pump"
    if "Tank" in s:
        return "tank"
    if "Recycle" in s or s == "OT_RCY":
        return "recycle"
    if "Spec" in s and "Stream" not in s:
        return "spec_block"
    return "unknown"


def map_objtype_to_prefix(obj_type_str, category):
    return {
        "material_stream": "MS",
        "energy_stream": "ES",
        "column": "COL",
        "heater": "HC",
        "pump": "PMP",
        "tank": "TANK",
        "recycle": "RECYCLE",
        "spec_block": None,
        "unknown": "UNK",
    }.get(category, "UNK")


# ============================================================================
# Material stream walks
# ============================================================================

def probe_prop_ms(ms, log):
    """Probe PROP_MS_0..50 via reflection, stop at first raise OR at 50 (Q3)."""
    results = {}
    for i in range(PROP_MS_MAX_INDEX + 1):
        key = f"PROP_MS_{i}"
        try:
            val = rcall(ms, "GetPropertyValue", key)
        except Exception:
            break
        unit = None
        try:
            u = rcall(ms, "GetPropertyUnit", key)
            unit = str(u) if u is not None else None
        except Exception:
            pass
        results[key] = {"value": coerce(val), "unit": unit}
    return results


def get_phases(ms):
    """Return list of dicts: [{idx, name, phase}].

    ms.Phases is masked by interface — read via reflection. Phases is a
    Dictionary<int, IPhase>; iterate by Keys.
    """
    out = []
    phases_dict = rget(ms, "Phases")
    if phases_dict is None:
        return out
    try:
        keys = list(phases_dict.Keys)
    except Exception:
        # Fallback: try enumerable
        try:
            for i, p in enumerate(phases_dict):
                out.append({"idx": i, "name": str(rget(p, "Name") or ""), "phase": p})
        except Exception:
            pass
        return out
    for k in keys:
        try:
            p = phases_dict[k]
            try:
                idx = int(k)
            except Exception:
                idx = k
            name = str(rget(p, "Name") or "")
            out.append({"idx": idx, "name": name, "phase": p})
        except Exception:
            continue
    return out


def detect_phase_layout(ms, phases, prop_ms_vals, log, owner_tag):
    """Identify OVERALL/VAPOR/LIQUID phase indices and whether multi-phase."""
    # Heuristic: vapor fraction often at PROP_MS_27 in DWSIM
    vf = None
    for k in ("PROP_MS_27", "PROP_MS_26", "PROP_MS_28"):
        v = prop_ms_vals.get(k, {}).get("value")
        if isinstance(v, (int, float)) and 0.0 <= v <= 1.0:
            vf = float(v)
            break

    overall_idx = None
    vapor_idx = None
    liquid_idx = None
    for p in phases:
        name = p["name"].lower()
        if overall_idx is None and ("mixture" in name or "overall" in name) and "liquid" not in name:
            overall_idx = p["idx"]
        if vapor_idx is None and ("vapor" in name or "vapour" in name):
            vapor_idx = p["idx"]
    # First non-overall, non-vapor liquid phase
    for p in phases:
        if p["idx"] in (overall_idx, vapor_idx):
            continue
        if "liquid" in p["name"].lower():
            liquid_idx = p["idx"]
            break
    # Default mappings if names are unhelpful
    if overall_idx is None and phases:
        overall_idx = phases[0]["idx"]
    if vapor_idx is None and len(phases) > 1:
        vapor_idx = 1  # DWSIM convention

    is_multi = (vf is not None) and (1e-6 < vf < 1.0 - 1e-6)
    return {
        "is_multiphase": is_multi,
        "vapor_fraction": vf,
        "overall_idx": overall_idx,
        "vapor_idx": vapor_idx,
        "liquid_idx": liquid_idx,
        "phase_names": [p["name"] for p in phases],
    }


def get_phase_field_value(phase_obj, field_name):
    """Try to read phase.Properties.<field_name>. Return coerced or None."""
    try:
        props = phase_obj.Properties
    except Exception:
        return None
    try:
        v = getattr(props, field_name, None)
        return coerce(v)
    except Exception:
        return None


def enumerate_phase_properties(phase_obj):
    """Best-effort enumeration of phase.Properties readable fields."""
    candidate_fields = [
        "temperature", "pressure", "massflow", "molarflow",
        "volumetric_flow", "density", "enthalpy", "entropy",
        "molar_enthalpy", "molar_entropy", "molecularWeight",
        "thermalConductivity", "kinematic_viscosity", "viscosity",
        "molarfraction", "massfraction", "compressibility",
        "compressibilityFactor", "heatCapacityCp", "heatCapacityCv",
        "ideal_gas_heat_capacity", "speedOfSound", "isothermal_compressibility",
    ]
    out = {}
    try:
        props = phase_obj.Properties
    except Exception:
        return out
    for f in candidate_fields:
        try:
            v = getattr(props, f, None)
            if v is None:
                continue
            cv = coerce(v)
            if cv is None:
                continue
            out[f] = cv
        except Exception:
            continue
    return out


def get_phase_compositions(phase_obj, compound_names):
    out = {}
    try:
        compounds = phase_obj.Compounds
    except Exception:
        return out
    for name in compound_names:
        try:
            cmp = compounds[name]
        except Exception:
            continue
        mole = coerce(safe_attr(cmp, "MoleFraction"))
        mass = coerce(safe_attr(cmp, "MassFraction"))
        out[name] = {"mole_fraction": mole, "mass_fraction": mass}
    return out


def walk_material_stream(ms, compound_names, log, owner_tag):
    """Full material stream extraction with phase awareness."""
    inv = {}
    inv["prop_ms"] = probe_prop_ms(ms, log)
    phases = get_phases(ms)
    layout = detect_phase_layout(ms, phases, inv["prop_ms"], log, owner_tag)
    inv["phase_layout"] = layout

    # Compositions per phase index that exists
    compositions = {}
    for p in phases:
        compositions[p["idx"]] = {
            "name": p["name"],
            "fractions": get_phase_compositions(p["phase"], compound_names),
        }
    inv["compositions_by_phase"] = compositions

    # Per-phase thermo (for multi-phase, harvest VAPOR + LIQUID phase props)
    per_phase_thermo = {}
    for p in phases:
        per_phase_thermo[p["idx"]] = {
            "name": p["name"],
            "fields": enumerate_phase_properties(p["phase"]),
        }
    inv["thermo_by_phase"] = per_phase_thermo

    # Compound count for Bug 4 guard
    try:
        inv["compound_count_in_phase0"] = int(phases[0]["phase"].Compounds.Count) if phases else 0
    except Exception:
        inv["compound_count_in_phase0"] = None

    return inv


# ============================================================================
# Energy stream walk
# ============================================================================

def walk_energy_stream(es, log):
    inv = {}
    ef = safe_attr(es, "EnergyFlow")
    inv["energy_flow_W"] = coerce(ef)
    # Some DWSIM versions also expose Power, Duty, Energy
    for k in ("Power", "Duty", "Energy"):
        v = safe_attr(es, k)
        if v is not None:
            inv[k] = coerce(v)
    return inv


# ============================================================================
# Column walk
# ============================================================================

def walk_column(col, compound_names, log):
    inv = {}
    inv["NumberOfStages"] = coerce(safe_attr(col, "NumberOfStages"))
    try:
        inv["Stages_Count"] = int(col.Stages.Count)
    except Exception:
        inv["Stages_Count"] = None

    # Per-stage data
    stages = []
    n = inv["NumberOfStages"] or 0
    for i in range(int(n)):
        try:
            st = col.Stages[i]
        except Exception as e:
            log.log(f"Column stage[{i}] access failed: {e}", level="WARN")
            continue
        sd = {
            "index": i,
            "T_K": coerce(safe_attr(st, "T")),
            "P_Pa": coerce(safe_attr(st, "P")),
            "V_mol_s": coerce(safe_attr(st, "V")),
            "L_mol_s": coerce(safe_attr(st, "L")),
            "name": str(safe_attr(st, "Name") or ""),
            "liquid_compositions": {},
            "vapor_compositions": {},
        }
        # Try several access patterns for stage compositions
        for attr_name, target_dict in (
            ("xc", "liquid_compositions"),
            ("yc", "vapor_compositions"),
            ("LiqCompositions", "liquid_compositions"),
            ("VapCompositions", "vapor_compositions"),
            ("Compositions", "liquid_compositions"),
        ):
            d = safe_attr(st, attr_name)
            if d is None:
                continue
            for cn in compound_names:
                try:
                    v = d[cn]
                    sd[target_dict][cn] = coerce(v)
                except Exception:
                    continue
        stages.append(sd)
    inv["stages"] = stages

    # Iteration counters
    for k in ("IC", "EC"):
        inv[k] = coerce(safe_attr(col, k))

    # Reflux ratio + duties — try multiple attribute names
    for k in ("RR", "RefluxRatio", "Reflux_Ratio"):
        v = safe_attr(col, k)
        if v is not None:
            inv["RefluxRatio"] = coerce(v)
            break
    for k in ("CondenserDuty", "Condenser_Duty"):
        v = safe_attr(col, k)
        if v is not None:
            inv["CondenserDuty"] = coerce(v)
            break
    for k in ("ReboilerDuty", "Reboiler_Duty"):
        v = safe_attr(col, k)
        if v is not None:
            inv["ReboilerDuty"] = coerce(v)
            break

    # Spec properties: probe ALL public properties via reflection,
    # capture writable ones for setpoint generation downstream.
    inv["properties"] = introspect_object_properties(col)
    return inv


# ============================================================================
# Generic introspection (for heaters, pumps, tanks, recycle blocks, spec blocks)
# ============================================================================

# Property names known to be safe to read on most DWSIM unit ops.
# We still attempt all public properties via reflection but skip ones that
# raise on read (logged at WARN to keep findings.md clean).
_INTROSPECT_SKIP_NAMES = {
    "GraphicObject",  # circular-ish, large
    "FlowSheet",
    "PropertyPackage",  # captured separately
    "Phases",          # captured separately
    "Stages",          # captured separately
    "Item",
}


def introspect_object_properties(obj):
    """Walk public properties via .NET reflection. Returns list of dicts."""
    out = []
    try:
        clr_type = obj.GetType()
        props = clr_type.GetProperties()
    except Exception:
        return out
    for prop in props:
        try:
            name = str(prop.Name)
        except Exception:
            continue
        if name in _INTROSPECT_SKIP_NAMES:
            continue
        try:
            can_read = bool(prop.CanRead)
            can_write = bool(prop.CanWrite)
            ptype = str(prop.PropertyType.Name)
        except Exception:
            can_read = False
            can_write = False
            ptype = ""
        # Skip indexed (parameterized) properties
        try:
            if prop.GetIndexParameters().Length > 0:
                continue
        except Exception:
            pass
        val = None
        read_err = None
        if can_read:
            try:
                raw = prop.GetValue(obj, None)
                val = coerce(raw)
            except Exception as e:
                read_err = type(e).__name__
        out.append({
            "name": name,
            "value": val,
            "type": ptype,
            "can_read": can_read,
            "can_write": can_write,
            "read_error": read_err,
        })
    return out


# ============================================================================
# Energy stream subsystem trace (Q2)
# ============================================================================

def derive_energy_subsystem(es_obj, all_objects, log):
    """Trace connections; inherit subsystem from connected unit op."""
    es_tag = get_obj_tag(es_obj)
    candidates = []

    # Try GraphicObject.InputConnectors / OutputConnectors
    try:
        go = getattr(es_obj, "GraphicObject", None)
        if go is not None:
            for connector_attr in ("InputConnectors", "OutputConnectors"):
                conns = getattr(go, connector_attr, None)
                if conns is None:
                    continue
                try:
                    n = conns.Count
                except Exception:
                    continue
                for i in range(n):
                    try:
                        c = conns[i]
                        if not bool(getattr(c, "IsAttached", False)):
                            continue
                        att = getattr(c, "AttachedConnector", None)
                        if att is None:
                            continue
                        # AttachedConnector has AttachedFrom / AttachedTo GraphicObjects
                        for end in ("AttachedFrom", "AttachedTo"):
                            other_go = getattr(att, end, None)
                            if other_go is None:
                                continue
                            other_name = str(getattr(other_go, "Name", "") or "")
                            other_tag = str(getattr(other_go, "Tag", "") or "")
                            # Find matching simulation object
                            for rec in all_objects:
                                if rec["internal_name"] == other_name or rec["tag"] == other_tag:
                                    if rec["subsystem"]:
                                        candidates.append(rec["subsystem"])
                                    break
                    except Exception:
                        continue
    except Exception as e:
        log.log(f"Energy connector trace failed for {es_tag}: {e}", level="WARN")

    # Pick most common subsystem; tie → None
    if not candidates:
        return None
    counts = {}
    for c in candidates:
        counts[c] = counts.get(c, 0) + 1
    best = max(counts.items(), key=lambda kv: kv[1])
    # If tied between different subsystems, return None
    top_count = best[1]
    if sum(1 for v in counts.values() if v == top_count) > 1:
        return None
    return best[0]


# ============================================================================
# Guards (Bug 4, Bug 6, Bug 8)
# ============================================================================

def run_guards(all_objects, compound_names, sim, log):
    expected_compound_count = len(compound_names)
    results = {}

    # Bug Class 4: every material stream has correct compound count
    bug4_failures = []
    for rec in all_objects:
        if rec["category"] != "material_stream":
            continue
        ms = rec["obj_ref"]
        try:
            n = int(ms.Phases[0].Compounds.Count)
        except Exception as e:
            bug4_failures.append({
                "tag": rec["tag"],
                "reason": f"Could not read compound count: {type(e).__name__}: {e}",
            })
            continue
        if n != expected_compound_count:
            bug4_failures.append({
                "tag": rec["tag"],
                "expected": expected_compound_count,
                "actual": n,
            })
    results["bug4_zombie_composition"] = {
        "passed": len(bug4_failures) == 0,
        "expected_compound_count": expected_compound_count,
        "failures": bug4_failures,
    }

    # Bug Class 6: Light Product has ≥10 compounds with mole frac > 0.01
    light_product_rec = None
    for rec in all_objects:
        if rec["category"] == "material_stream" and rec["tag"].strip().lower() == "light product":
            light_product_rec = rec
            break
    bug6 = {"passed": False, "found_stream": False, "compounds_above_threshold": None,
            "top10": [], "threshold": BUG6_MOLE_FRAC_THRESHOLD}
    if light_product_rec is not None:
        bug6["found_stream"] = True
        ms = light_product_rec["obj_ref"]
        try:
            phase = ms.Phases[0]
            comp_pairs = []
            for cn in compound_names:
                try:
                    cmp = phase.Compounds[cn]
                    mole = coerce(safe_attr(cmp, "MoleFraction"))
                    if mole is not None:
                        comp_pairs.append((cn, mole))
                except Exception:
                    continue
            comp_pairs.sort(key=lambda kv: (kv[1] if kv[1] is not None else 0), reverse=True)
            count_above = sum(1 for _, m in comp_pairs if (m or 0) > BUG6_MOLE_FRAC_THRESHOLD)
            bug6["compounds_above_threshold"] = count_above
            bug6["top10"] = [{"compound": cn, "mole_fraction": m} for cn, m in comp_pairs[:10]]
            bug6["passed"] = count_above >= BUG6_LIGHT_PRODUCT_MIN_COMPS
        except Exception as e:
            bug6["error"] = f"{type(e).__name__}: {e}"
    else:
        log.log("Bug 6 guard: Light Product stream not found by tag match", level="WARN")
    results["bug6_false_convergence"] = bug6

    # Bug Class 8: NumberOfStages == Stages.Count for every column
    bug8_failures = []
    for rec in all_objects:
        if rec["category"] != "column":
            continue
        col = rec["obj_ref"]
        nos = coerce(safe_attr(col, "NumberOfStages"))
        try:
            sc = int(col.Stages.Count)
        except Exception as e:
            bug8_failures.append({
                "tag": rec["tag"],
                "reason": f"Could not read Stages.Count: {type(e).__name__}: {e}",
            })
            continue
        if int(nos or 0) != sc:
            bug8_failures.append({
                "tag": rec["tag"],
                "NumberOfStages": nos,
                "Stages_Count": sc,
            })
    results["bug8_stage_count_parity"] = {
        "passed": len(bug8_failures) == 0,
        "failures": bug8_failures,
    }

    return results


# ============================================================================
# Tag, setpoint, constraint dictionary builders
# ============================================================================

def _is_thermal_oil(rec):
    return rec.get("subsystem") == "thermal_oil"


def _is_petroleum(rec):
    return rec.get("subsystem") == "petroleum"


def _common_owner_fields(rec):
    return {
        "owner_tag": rec["tag"],
        "owner_type": rec["object_type"],
        "subsystem": rec.get("subsystem"),
        "property_package": rec.get("property_package"),
    }


# Setpoint candidate name patterns
_SETPOINT_NAME_PATTERNS = re.compile(
    r"(Spec_|^Spec$|RefluxRatio|^RR$|Temperature|Pressure|"
    r"OutletTemperature|PressureDrop|^Efficiency$|^Power$|"
    r"DeltaP|MaximumIterations|ConvergenceTolerance|Tolerance|"
    r"Active|StageNumber|HeatSpec|MassFlow|MoleFlow|VolumeFlow|"
    r"OutletPressure|InletPressure|Duty|HeatDuty|Mode|CalculationMode)"
)


def _suggest_bounds(name, value, ptype):
    """Return (bounds_dict_or_None, kind_str) based on Q4 rules."""
    n = name or ""
    if value is None or not isinstance(value, (int, float)):
        return None, "non-numeric"
    if "Temperature" in n or "T_" in n or n.endswith("_T"):
        return {
            "type": "delta",
            "low": value - TEMP_BOUND_DELTA_K,
            "high": value + TEMP_BOUND_DELTA_K,
            "unit_assumed": "K",
        }, "temperature"
    if "Efficiency" in n:
        return {
            "type": "absolute",
            "low": EFFICIENCY_BOUNDS[0],
            "high": EFFICIENCY_BOUNDS[1],
        }, "efficiency"
    if "MoleFraction" in n or "MoleFrac" in n:
        return {
            "type": "absolute",
            "low": MOLE_FRAC_BOUNDS[0],
            "high": MOLE_FRAC_BOUNDS[1],
        }, "mole_fraction"
    # Default: ±20 %
    if value == 0:
        return {
            "type": "delta",
            "low": -1.0,
            "high": 1.0,
            "note": "current value 0; bounds are ±1 placeholder",
        }, "default_pct_zero"
    delta = abs(value) * PCT_DEFAULT_BOUNDS
    return {
        "type": "pct",
        "pct": PCT_DEFAULT_BOUNDS,
        "low": value - delta,
        "high": value + delta,
    }, "default_pct"


def build_dictionaries(inventory, all_objects, compound_names, log):
    tag_dict = []
    setpoint_dict = []
    constraint_dict = []

    inv_by_id = {o["id"]: o for o in inventory["objects"]}

    for rec in all_objects:
        cat = rec["category"]
        inv_obj = inv_by_id.get(rec["id"])
        if inv_obj is None:
            continue

        if cat == "material_stream":
            _emit_material_stream_tags(rec, inv_obj, compound_names,
                                       tag_dict, setpoint_dict, log)
        elif cat == "energy_stream":
            _emit_energy_stream_tags(rec, inv_obj, tag_dict, setpoint_dict, log)
        elif cat == "column":
            _emit_column_tags(rec, inv_obj, compound_names,
                              tag_dict, setpoint_dict, log)
        elif cat in ("heater", "pump", "tank", "recycle"):
            _emit_generic_tags(rec, inv_obj, cat, tag_dict, setpoint_dict, log)
        elif cat == "spec_block":
            _emit_constraint(rec, inv_obj, all_objects, constraint_dict, log)
        else:
            # Unknown — emit minimal tags + log
            log.log(f"Unknown category for {rec['tag']!r} (type {rec['object_type']})",
                    level="WARN")
            _emit_generic_tags(rec, inv_obj, "other", tag_dict, setpoint_dict, log)

    return tag_dict, setpoint_dict, constraint_dict


def _tag_entry(prefix, owner_tag, parts, *, owner_rec, property_key, description,
               unit_si, current_value, category, static_composition=False,
               composition_meaningful=None):
    entry = {
        "tag_id": make_tag_id(prefix, owner_tag, *parts),
        "owner_tag": owner_tag,
        "owner_type": owner_rec["object_type"],
        "phase": parts[0] if parts and parts[0] in ("OVERALL", "VAPOR", "LIQUID") else None,
        "property_key": property_key,
        "description": description,
        "unit_si": unit_si,
        "current_value": current_value,
        "category": category,
        "subsystem": owner_rec.get("subsystem"),
        "property_package": owner_rec.get("property_package"),
        "static_composition": static_composition,
    }
    if category == "stream_composition":
        entry["composition_meaningful"] = composition_meaningful
    else:
        entry["composition_meaningful"] = None
    return entry


_PROP_MS_DESCRIPTIONS = {
    "PROP_MS_0": "Temperature",
    "PROP_MS_1": "Pressure",
    "PROP_MS_2": "Mass Flow",
    "PROP_MS_3": "Mole Flow",
    "PROP_MS_4": "Volumetric Flow",
    "PROP_MS_5": "Density",
    "PROP_MS_6": "Specific Enthalpy",
    "PROP_MS_7": "Specific Entropy",
    "PROP_MS_8": "Molar Enthalpy",
    "PROP_MS_9": "Molar Entropy",
    "PROP_MS_10": "Molecular Weight",
    "PROP_MS_27": "Vapor Mole Fraction",
}


def _emit_material_stream_tags(rec, inv_obj, compound_names,
                               tag_dict, setpoint_dict, log):
    owner_tag = rec["tag"]
    inv = inv_obj["inventory"]
    layout = inv["phase_layout"]
    is_multi = layout["is_multiphase"]
    static = _is_thermal_oil(rec)
    comp_meaningful = not static

    # OVERALL thermo (for both single-phase and multi-phase)
    for key, info in inv["prop_ms"].items():
        desc = _PROP_MS_DESCRIPTIONS.get(key, key)
        if is_multi:
            tag_dict.append(_tag_entry(
                "MS", owner_tag, ("OVERALL", key),
                owner_rec=rec, property_key=key, description=desc,
                unit_si=info.get("unit"), current_value=info.get("value"),
                category="stream_thermo",
            ))
        else:
            tag_dict.append(_tag_entry(
                "MS", owner_tag, (key,),
                owner_rec=rec, property_key=key, description=desc,
                unit_si=info.get("unit"), current_value=info.get("value"),
                category="stream_thermo",
            ))

    # VAPOR / LIQUID per-phase thermo (multi-phase only)
    if is_multi:
        for phase_label, phase_idx in (("VAPOR", layout["vapor_idx"]),
                                       ("LIQUID", layout["liquid_idx"])):
            if phase_idx is None:
                continue
            phase_thermo = inv["thermo_by_phase"].get(phase_idx, {}).get("fields", {})
            # Emit per PROP_MS_X with phase field mapping (briefing-aligned)
            for prop_key, field_name in PROP_MS_PHASE_FIELD.items():
                v = phase_thermo.get(field_name)
                if v is None:
                    continue
                desc = _PROP_MS_DESCRIPTIONS.get(prop_key, prop_key) + f" ({phase_label.lower()} phase)"
                tag_dict.append(_tag_entry(
                    "MS", owner_tag, (phase_label, prop_key),
                    owner_rec=rec, property_key=prop_key, description=desc,
                    unit_si=None, current_value=v,
                    category="stream_thermo",
                ))

    # Compositions
    if is_multi:
        for phase_label, phase_idx in (("OVERALL", layout["overall_idx"]),
                                       ("VAPOR", layout["vapor_idx"]),
                                       ("LIQUID", layout["liquid_idx"])):
            if phase_idx is None:
                continue
            comps = inv["compositions_by_phase"].get(phase_idx, {}).get("fractions", {})
            _emit_composition_tags(rec, owner_tag, comps, compound_names,
                                   tag_dict, phase_label=phase_label,
                                   static=static, comp_meaningful=comp_meaningful)
    else:
        # Single-phase: use Phases[0] (overall)
        phase_idx = layout["overall_idx"] if layout["overall_idx"] is not None else 0
        comps = inv["compositions_by_phase"].get(phase_idx, {}).get("fractions", {})
        _emit_composition_tags(rec, owner_tag, comps, compound_names,
                               tag_dict, phase_label=None,
                               static=static, comp_meaningful=comp_meaningful)

    # Setpoint candidates: input streams (Calculated == False) → PROP_MS_0/1/2 writable
    if not rec.get("calculated"):
        for setpoint_key in ("PROP_MS_0", "PROP_MS_1", "PROP_MS_2"):
            info = inv["prop_ms"].get(setpoint_key)
            if info is None:
                continue
            v = info.get("value")
            bounds, kind = _suggest_bounds(_PROP_MS_DESCRIPTIONS.get(setpoint_key, setpoint_key), v, "Double")
            setpoint_dict.append({
                "owner_tag": owner_tag,
                "owner_type": rec["object_type"],
                "subsystem": rec.get("subsystem"),
                "property_key": setpoint_key,
                "description": _PROP_MS_DESCRIPTIONS.get(setpoint_key, setpoint_key),
                "current_value": v,
                "unit_si": info.get("unit"),
                "bounds": bounds,
                "bounds_kind": kind,
                "rationale": "input stream (Calculated=False) primary thermo spec",
            })


def _emit_composition_tags(rec, owner_tag, comps, compound_names, tag_dict,
                           *, phase_label, static, comp_meaningful):
    for cn in compound_names:
        cv = comps.get(cn, {})
        for kind, key, desc in (("MoleFraction", "mole_fraction", "Mole Fraction"),
                                ("MassFraction", "mass_fraction", "Mass Fraction")):
            v = cv.get(key)
            if phase_label is not None:
                parts = (phase_label, kind, cn)
            else:
                parts = (kind, cn)
            tag_dict.append(_tag_entry(
                "MS", owner_tag, parts,
                owner_rec=rec, property_key=f"{kind}.{cn}",
                description=f"{desc} of {cn}",
                unit_si="dimensionless", current_value=v,
                category="stream_composition", static_composition=static,
                composition_meaningful=comp_meaningful,
            ))


def _emit_energy_stream_tags(rec, inv_obj, tag_dict, setpoint_dict, log):
    owner_tag = rec["tag"]
    inv = inv_obj["inventory"]
    ef = inv.get("energy_flow_W")
    tag_dict.append(_tag_entry(
        "ES", owner_tag, ("EnergyFlow",),
        owner_rec=rec, property_key="EnergyFlow", description="Energy Flow",
        unit_si="W", current_value=ef, category="energy",
    ))
    # Energy streams are not directly setpoint-able (driven by connected ops)


def _emit_column_tags(rec, inv_obj, compound_names, tag_dict, setpoint_dict, log):
    owner_tag = rec["tag"]
    state = inv_obj["inventory"]["column_state"]

    # Global tags
    for key, desc, unit, cat in (
        ("NumberOfStages", "Number of Stages", "count", "column_global"),
        ("Stages_Count", "Stages Collection Count", "count", "column_global"),
        ("IC", "Internal Iteration Count", "count", "column_global"),
        ("EC", "External Iteration Count", "count", "column_global"),
        ("RefluxRatio", "Reflux Ratio", "dimensionless", "column_global"),
        ("CondenserDuty", "Condenser Duty", "W", "column_global"),
        ("ReboilerDuty", "Reboiler Duty", "W", "column_global"),
    ):
        v = state.get(key)
        if v is None:
            continue
        tag_dict.append(_tag_entry(
            "COL", owner_tag, (key,),
            owner_rec=rec, property_key=key, description=desc,
            unit_si=unit, current_value=v, category=cat,
        ))

    # Per-stage tags
    for st in state.get("stages", []):
        i = st["index"]
        stage_seg = f"STAGE_{i}"
        for key, desc, unit in (
            ("T_K", "Temperature", "K"),
            ("P_Pa", "Pressure", "Pa"),
            ("V_mol_s", "Vapor Flow", "mol/s"),
            ("L_mol_s", "Liquid Flow", "mol/s"),
        ):
            v = st.get(key)
            if v is None:
                continue
            tag_dict.append(_tag_entry(
                "COL", owner_tag, (stage_seg, key),
                owner_rec=rec, property_key=key, description=f"Stage {i} {desc}",
                unit_si=unit, current_value=v, category="column_stage",
            ))
        # Stage compositions (liquid; vapor may also be present)
        for cn in compound_names:
            v = st.get("liquid_compositions", {}).get(cn)
            if v is None:
                continue
            tag_dict.append(_tag_entry(
                "COL", owner_tag, (stage_seg, "LiqMoleFraction", cn),
                owner_rec=rec, property_key=f"LiqMoleFraction.{cn}",
                description=f"Stage {i} liquid mole fraction of {cn}",
                unit_si="dimensionless", current_value=v,
                category="column_stage",
            ))

    # Spec / writable properties → setpoint candidates
    for p in inv_obj["inventory"]["column_state"].get("properties", []):
        name = p["name"]
        if not p["can_write"]:
            continue
        # Filter to spec-relevant names to avoid noise
        if not _SETPOINT_NAME_PATTERNS.search(name):
            continue
        v = p["value"]
        bounds, kind = _suggest_bounds(name, v, p.get("type", ""))
        setpoint_dict.append({
            "owner_tag": owner_tag,
            "owner_type": rec["object_type"],
            "subsystem": rec.get("subsystem"),
            "property_key": name,
            "description": name,
            "current_value": v,
            "unit_si": None,
            "bounds": bounds,
            "bounds_kind": kind,
            "rationale": "column writable property matching spec pattern",
        })


def _emit_generic_tags(rec, inv_obj, cat_label, tag_dict, setpoint_dict, log):
    """For heaters, pumps, tanks, recycle blocks — emit reflection-discovered tags."""
    owner_tag = rec["tag"]
    prefix = map_objtype_to_prefix(rec["object_type"], rec["category"]) or "UNK"
    props = inv_obj["inventory"].get("properties", [])
    cat_for_tag = {
        "heater": "heater",
        "pump": "pump",
        "tank": "tank",
        "recycle": "recycle",
        "other": "other",
    }.get(cat_label, "other")

    for p in props:
        name = p["name"]
        v = p["value"]
        if not p["can_read"]:
            continue
        # Skip non-scalar/non-string reads (would be huge, e.g. Phases collection)
        # Already filtered upstream; coerced to None if unrepresentable.
        if v is None and p.get("read_error"):
            continue
        tag_dict.append(_tag_entry(
            prefix, owner_tag, (name,),
            owner_rec=rec, property_key=name, description=name,
            unit_si=None, current_value=v, category=cat_for_tag,
        ))
        if p["can_write"] and _SETPOINT_NAME_PATTERNS.search(name):
            bounds, kind = _suggest_bounds(name, v, p.get("type", ""))
            setpoint_dict.append({
                "owner_tag": owner_tag,
                "owner_type": rec["object_type"],
                "subsystem": rec.get("subsystem"),
                "property_key": name,
                "description": name,
                "current_value": v,
                "unit_si": None,
                "bounds": bounds,
                "bounds_kind": kind,
                "rationale": f"writable property on {cat_for_tag} matching spec pattern",
            })


def _emit_constraint(rec, inv_obj, all_objects, constraint_dict, log):
    """SpecificationBlock → constraint dictionary entry."""
    props = {p["name"]: p for p in inv_obj["inventory"].get("properties", [])}

    def gv(name):
        return props.get(name, {}).get("value")

    # Try common SpecBlock attribute names
    target_obj = None
    target_var = None
    source_obj = None
    source_var = None
    active = None
    for n in ("TargetObject", "TargetObjectName", "Target_Object", "TargetObjectId"):
        v = gv(n)
        if v is not None:
            target_obj = v
            break
    for n in ("TargetVar", "TargetVariable", "TargetProperty"):
        v = gv(n)
        if v is not None:
            target_var = v
            break
    for n in ("SourceObject", "SourceObjectName", "SourceObjectId"):
        v = gv(n)
        if v is not None:
            source_obj = v
            break
    for n in ("SourceVar", "SourceVariable", "SourceProperty"):
        v = gv(n)
        if v is not None:
            source_var = v
            break
    for n in ("Active", "Enabled", "IsActive"):
        v = gv(n)
        if v is not None:
            active = v
            break

    constraint_dict.append({
        "constraint_id": rec["tag"],
        "internal_name": rec["internal_name"],
        "object_type": rec["object_type"],
        "subsystem": rec.get("subsystem"),
        "target_object": target_obj,
        "target_property": target_var,
        "source_object": source_obj,
        "source_property": source_var,
        "active": active,
        "all_properties": [
            {"name": p["name"], "value": p["value"], "can_write": p["can_write"]}
            for p in inv_obj["inventory"].get("properties", [])
        ],
    })


# ============================================================================
# Findings.md writer
# ============================================================================

def write_findings(out_dir, inventory, tag_dict, setpoint_dict, constraint_dict,
                   all_objects, guard_results, log, ground_truth_check):
    meta = inventory["meta"]

    # Object breakdown
    cat_counts = meta["objtype_counts"]

    # Tag counts by category and subsystem
    tc_by_cat_sub = {}
    for t in tag_dict:
        key = (t.get("subsystem") or "unknown", t["category"])
        tc_by_cat_sub[key] = tc_by_cat_sub.get(key, 0) + 1
    tc_static = sum(1 for t in tag_dict if t.get("static_composition"))

    petroleum_streams = [r for r in all_objects
                         if r["category"] == "material_stream" and _is_petroleum(r)]
    thermal_streams = [r for r in all_objects
                       if r["category"] == "material_stream" and _is_thermal_oil(r)]
    energy_streams_recs = [r for r in all_objects if r["category"] == "energy_stream"]

    # Column summary
    col_summary = ""
    for o in inventory["objects"]:
        if o["category"] != "column":
            continue
        cs = o["inventory"]["column_state"]
        col_summary = (f"{o['tag']!r} — NumberOfStages={cs.get('NumberOfStages')}, "
                       f"Stages.Count={cs.get('Stages_Count')}, "
                       f"RR={cs.get('RefluxRatio')}, "
                       f"CondenserDuty={cs.get('CondenserDuty')} W, "
                       f"ReboilerDuty={cs.get('ReboilerDuty')} W")
        break

    # Spec blocks summary
    spec_lines = []
    for c in constraint_dict:
        spec_lines.append(
            f"- **{c['constraint_id']}** — type {c['object_type']}, "
            f"target={c['target_object']!r}/{c['target_property']!r}, "
            f"source={c['source_object']!r}/{c['source_property']!r}, "
            f"active={c['active']}"
        )

    # Guard summary
    g4 = guard_results["bug4_zombie_composition"]
    g6 = guard_results["bug6_false_convergence"]
    g8 = guard_results["bug8_stage_count_parity"]

    blocked_lines = []
    if not g4["passed"]:
        blocked_lines.append(f"- Bug Class 4 guard FAILED: {g4['failures']}")
    if not g6["passed"]:
        blocked_lines.append(f"- Bug Class 6 guard FAILED: count_above={g6.get('compounds_above_threshold')}, threshold={BUG6_LIGHT_PRODUCT_MIN_COMPS}")
    if not g8["passed"]:
        blocked_lines.append(f"- Bug Class 8 guard FAILED: {g8['failures']}")

    # Find unknown-category objects
    unknown_recs = [r for r in all_objects if r["category"] == "unknown"]
    for r in unknown_recs:
        blocked_lines.append(f"- Unknown ObjectType not handled: {r['tag']!r} (type {r['object_type']})")

    # Energy streams without subsystem
    es_no_sub = [r for r in energy_streams_recs if not r.get("subsystem")]
    for r in es_no_sub:
        blocked_lines.append(f"- Energy stream {r['tag']!r} has no subsystem (topology trace + name fallback both failed)")

    # Non-numeric writables (Q4 architect review)
    nonnum_setpoints = [s for s in setpoint_dict if s.get("bounds_kind") == "non-numeric"]

    decisions = []
    if nonnum_setpoints:
        decisions.append(f"- {len(nonnum_setpoints)} writable property(ies) are non-numeric (enums/strings/bools); bounds=null. List in setpoint_dictionary. Architect call: include in perturbation harness or hold?")
    if not g4["passed"] or not g6["passed"] or not g8["passed"]:
        decisions.append("- One or more chemistry guards failed. Substrate inventory is unreliable; do not proceed to Stage 1 streamer.")
    # Tag count out-of-range
    total_tags = len(tag_dict)
    if total_tags < 800:
        decisions.append(f"- Tag count {total_tags} below floor [800, 2500]; likely a walk omission.")
    if total_tags > 2500:
        decisions.append(f"- Tag count {total_tags} above ceiling [800, 2500]; likely over-emission.")
    # Constraint count
    if len(constraint_dict) != 2:
        decisions.append(f"- Constraint count is {len(constraint_dict)}, expected 2 (SPEC-02, SPEC-020). Investigate.")
    # Property package presence
    pp_names_set = {(p.get("name") or "").lower() for p in meta["property_packages"]}
    has_pr = any("peng" in n or "robinson" in n or n == "pr" for n in pp_names_set)
    has_cp = any("coolprop" in n or "incompressible" in n for n in pp_names_set)
    if not has_pr:
        decisions.append("- Peng-Robinson property package NOT detected. Substrate may be wrong file.")
    if not has_cp:
        decisions.append("- CoolProp Incompressible property package NOT detected. Substrate may be wrong file.")

    # Solve duration flag
    if meta["solve_duration_s"] > 10:
        decisions.append(f"- Solve duration {meta['solve_duration_s']:.2f}s exceeds 10s expectation. Investigate.")

    # Ground-truth cross-check
    gt_lines = []
    for k, v in ground_truth_check.items():
        ok = v.get("ok")
        symbol = "PASS" if ok else "FAIL"
        gt_lines.append(f"- {symbol} {k}: expected ~{v['expected']}, got {v['actual']}, tolerance={v.get('tolerance')}")
        if not ok:
            decisions.append(f"- Ground-truth mismatch on {k}: expected {v['expected']}, got {v['actual']}")

    # Compose findings.md
    md_lines = []
    md_lines.append("# Phase 0a Findings — Substrate Inventory")
    md_lines.append("")
    md_lines.append("## 1. What was probed")
    md_lines.append("")
    md_lines.append(f"- File: `{meta['substrate']}`")
    md_lines.append(f"- Probe version: {meta['probe_version']}")
    md_lines.append(f"- Timestamp: {meta['timestamp_utc']}")
    md_lines.append(f"- Compounds: {meta['compound_count']} — first 3: {meta['compound_ids'][:3]}, last 3: {meta['compound_ids'][-3:] if meta['compound_count'] >= 3 else []}")
    md_lines.append(f"- SimulationObjects: {meta['sim_object_count']}; breakdown:")
    for cat, n in sorted(cat_counts.items()):
        md_lines.append(f"    - {cat}: {n}")
    md_lines.append("- Property packages:")
    for pp in meta["property_packages"]:
        md_lines.append(f"    - id={pp['id']!r}, name={pp['name']!r}, type={pp['type']}")
    md_lines.append(f"- Solve duration: {meta['solve_duration_s']:.3f}s")
    md_lines.append(f"- Pre-solved on load: {meta['pre_solved_on_load']}")
    md_lines.append("")
    md_lines.append("## 2. What was found")
    md_lines.append("")
    md_lines.append("### Petroleum subsystem")
    petr_tags = [r["tag"] for r in petroleum_streams]
    md_lines.append(f"**Material streams ({len(petroleum_streams)}):** {', '.join(petr_tags) or '(none)'}")
    md_lines.append(f"**Column:** {col_summary or '(none found)'}")
    md_lines.append("**Confirms ground truth:** see cross-check table below")
    md_lines.append("")
    md_lines.append("### Thermal oil subsystem")
    therm_tags = [r["tag"] for r in thermal_streams]
    md_lines.append(f"**Material streams ({len(thermal_streams)}):** {', '.join(therm_tags) or '(none)'}")
    # Heaters / pumps / tanks / recycle
    for cat, label in (("heater", "Heaters"), ("pump", "Pumps"),
                       ("tank", "Tanks"), ("recycle", "Recycle Blocks")):
        recs = [r for r in all_objects if r["category"] == cat]
        if recs:
            md_lines.append(f"**{label}:** {', '.join(r['tag'] for r in recs)}")
    md_lines.append("")
    md_lines.append("### Energy streams")
    for r in energy_streams_recs:
        # Find energy_flow value
        ef = None
        for o in inventory["objects"]:
            if o["id"] == r["id"]:
                ef = o["inventory"].get("energy_flow_W")
                break
        md_lines.append(f"- {r['tag']!r}: EnergyFlow = {ef} W, subsystem = {r.get('subsystem')}")
    md_lines.append("")
    md_lines.append("### Constraints (SpecificationBlocks)")
    if spec_lines:
        md_lines.extend(spec_lines)
    else:
        md_lines.append("(none detected)")
    md_lines.append("")
    md_lines.append(f"### Total tag count: {len(tag_dict)}")
    md_lines.append("Breakdown by subsystem / category:")
    for (sub, cat), n in sorted(tc_by_cat_sub.items()):
        md_lines.append(f"- {sub} / {cat}: {n}")
    md_lines.append(f"- Static-composition tags (thermal-oil compositions): {tc_static}")
    md_lines.append("")
    md_lines.append(f"### Setpoint count: {len(setpoint_dict)}")
    md_lines.append("Top 10 by ownership:")
    for s in setpoint_dict[:10]:
        md_lines.append(f"- `{s['owner_tag']}` / `{s['property_key']}` = {s['current_value']} (bounds_kind={s['bounds_kind']})")
    md_lines.append("")
    md_lines.append(f"### Constraint count: {len(constraint_dict)}")
    for c in constraint_dict:
        md_lines.append(f"- `{c['constraint_id']}`: {c['object_type']}, target={c['target_object']!r}/{c['target_property']!r}")
    md_lines.append("")
    md_lines.append("### Chemistry guards")
    md_lines.append(f"- Bug 4 (zombie composition): {'PASS' if g4['passed'] else 'FAIL'} — {len(g4['failures'])} failures, expected_compound_count={g4['expected_compound_count']}")
    md_lines.append(f"- Bug 6 (false convergence on Light Product): {'PASS' if g6['passed'] else 'FAIL'} — {g6.get('compounds_above_threshold')} compounds above {BUG6_MOLE_FRAC_THRESHOLD} mole frac (need ≥{BUG6_LIGHT_PRODUCT_MIN_COMPS})")
    if g6.get("top10"):
        md_lines.append("  Top 10 compositions in Light Product:")
        for entry in g6["top10"]:
            md_lines.append(f"    - {entry['compound']}: {entry['mole_fraction']:.4f}")
    md_lines.append(f"- Bug 8 (Stages.Count == NumberOfStages): {'PASS' if g8['passed'] else 'FAIL'} — {len(g8['failures'])} failures")
    md_lines.append("")
    md_lines.append("### Ground-truth cross-check")
    md_lines.extend(gt_lines if gt_lines else ["(no checks executed)"])
    md_lines.append("")
    md_lines.append("## 3. What is blocked")
    md_lines.append("")
    if blocked_lines:
        md_lines.extend(blocked_lines)
    else:
        md_lines.append("(none)")
    md_lines.append("")
    md_lines.append("## 4. Proposed paths forward")
    md_lines.append("")
    md_lines.append("- Streamer Stage 1 should consume `phase0a_inventory.json` and emit the snapshot schema in STREAMING_PLAN.md Part C, extended with the `subsystem` field on every stream/op. The schema delta is: `subsystem: 'petroleum' | 'thermal_oil'` at the object level; per-tag entries inherit it.")
    md_lines.append(f"- Cycle interval recommendation: solve took {meta['solve_duration_s']:.2f}s; the briefing's 30 s default holds.")
    md_lines.append("- For multi-phase Oil, this probe emits OVERALL/VAPOR/LIQUID per the briefing; downstream snapshot schema needs a `phase` discriminator on stream tags.")
    md_lines.append("- Thermal-oil streams have static_composition=true / composition_meaningful=false. Streamer should de-prioritise these tags but emit them for completeness; dashboards can hide them.")
    md_lines.append("")
    md_lines.append("## 5. Architect decision point")
    md_lines.append("")
    if decisions:
        md_lines.extend(decisions)
    else:
        md_lines.append("(none)")
    md_lines.append("")

    findings_path = out_dir / "phase0a_findings.md"
    with open(str(findings_path), "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))
    log.log(f"Wrote {findings_path}")


def write_findings_failure(out_dir, substrate, solve_duration_s, err_msg, err_list, log):
    """Minimal findings.md when solve fails — keeps 5-section invariant."""
    findings_path = out_dir / "phase0a_findings.md"
    md = [
        "# Phase 0a Findings — Substrate Inventory (SOLVE FAILED)",
        "",
        "## 1. What was probed",
        "",
        f"- File: `{substrate}`",
        f"- Solve duration: {solve_duration_s:.3f}s",
        "- Solve outcome: FAILED — sim.Solved is False",
        "",
        "## 2. What was found",
        "",
        "(inventory not produced — solve failed)",
        "",
        "## 3. What is blocked",
        "",
        f"- Solver returned {len(err_list)} exception(s); sim.ErrorMessage: {err_msg!r}",
        "",
        "## 4. Proposed paths forward",
        "",
        "- Verify substrate file integrity",
        "- Re-run probe (3-attempt cap from KB §10)",
        "- If failure persists, escalate to architect with `phase0a_probe.log`",
        "",
        "## 5. Architect decision point",
        "",
        "- Solve failed on the substrate. Cannot inventory. Need decision on whether to: (a) re-acquire substrate, (b) revisit toolchain, or (c) accept partial findings.",
        "",
    ]
    with open(str(findings_path), "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    log.log(f"Wrote failure findings: {findings_path}", level="ERROR")


# ============================================================================
# Inventory serialization (strip .NET refs)
# ============================================================================

def strip_obj_refs(obj):
    """Recursively remove non-JSON-able .NET object references."""
    if isinstance(obj, dict):
        return {k: strip_obj_refs(v) for k, v in obj.items() if k != "obj_ref"}
    if isinstance(obj, list):
        return [strip_obj_refs(v) for v in obj]
    return obj


# ============================================================================
# Ground-truth cross-check
# ============================================================================

def check_ground_truth(inventory, all_objects, log):
    """Validate inventory against architect-provided ground truth."""
    expected = {
        "condenser_duty_W": (29_760_000.0, 0.05),       # 29.76 MW, ±5%
        "reboiler_duty_W": (-27_280_000.0, 0.05),       # -27.28 MW, ±5%
        "therminol_mass_flow_kg_s": (200.0, 0.05),      # 200 kg/s, ±5%
        "oil_vapor_fraction": (0.172, 0.05),            # 0.172, ±5% absolute
        "column_stages": (12, 0.0),                     # 12 stages, exact
        "compound_count": (30, 0.0),                    # 30, exact
    }
    actual = {}
    # Find column
    col_inv = None
    for o in inventory["objects"]:
        if o["category"] == "column":
            col_inv = o
            break
    if col_inv is not None:
        cs = col_inv["inventory"]["column_state"]
        actual["condenser_duty_W"] = cs.get("CondenserDuty")
        actual["reboiler_duty_W"] = cs.get("ReboilerDuty")
        actual["column_stages"] = cs.get("NumberOfStages")
    # Compound count
    actual["compound_count"] = inventory["meta"]["compound_count"]
    # Therminol mass flow & Oil vapor fraction
    for o in inventory["objects"]:
        if o["category"] != "material_stream":
            continue
        tag = o["tag"]
        prop_ms = o["inventory"].get("prop_ms", {})
        if tag == "Therminol VP1":
            actual["therminol_mass_flow_kg_s"] = prop_ms.get("PROP_MS_2", {}).get("value")
        if tag == "Oil":
            # vapor fraction: try PROP_MS_27 first
            v = prop_ms.get("PROP_MS_27", {}).get("value")
            if v is None:
                v = o["inventory"].get("phase_layout", {}).get("vapor_fraction")
            actual["oil_vapor_fraction"] = v

    out = {}
    for k, (exp, tol) in expected.items():
        a = actual.get(k)
        ok = False
        if a is None:
            ok = False
        elif tol == 0.0:
            ok = (a == exp)
        else:
            try:
                ok = abs(a - exp) <= max(abs(exp) * tol, 1e-9)
            except Exception:
                ok = False
        out[k] = {"expected": exp, "actual": a, "tolerance": tol, "ok": ok}
    return out


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Phase 0a substrate inventory probe")
    parser.add_argument("--substrate", default=DEFAULT_SUBSTRATE,
                        help="Path to substrate .dwxmz file")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR,
                        help="Output directory for the 7 artifacts")
    args = parser.parse_args()

    substrate = Path(args.substrate).expanduser().resolve()
    out_dir = Path(args.output_dir).expanduser()

    print(f"[Phase 0a probe] substrate: {substrate}")
    print(f"[Phase 0a probe] output:    {out_dir}")
    print(f"[Phase 0a probe] expecting 7 artifacts (refuse-if-exists)")

    # ===== Pre-flight (refuse-if-exists; runs FIRST, before any I/O) =====
    preflight(substrate, out_dir)

    # mkdir is now safe
    out_dir.mkdir(parents=True, exist_ok=True)

    log_path = out_dir / "phase0a_probe.log"
    log = Logger(log_path)

    try:
        log.log("=" * 70)
        log.log("Phase 0a probe started")
        log.log(f"Substrate: {substrate}")
        log.log(f"Output dir: {out_dir}")

        # ===== Save before solve (KB §8) — file copy, before LoadFlowsheet =====
        baseline_path = out_dir / "phase0a_substrate_pre_solve.dwxmz"
        shutil.copy2(str(substrate), str(baseline_path))
        log.log(f"Pre-solve baseline saved: {baseline_path}")

        # ===== Bootstrap =====
        import clr
        for dll in DWSIM_DLLS:
            clr.AddReference(dll)
            log.log(f"Loaded DLL: {dll}")

        from DWSIM.Automation import Automation3
        from System import Action

        sim_auto = Automation3()
        log.log("Automation3 instance created")

        # ===== Load =====
        log.log("Loading flowsheet...")
        sim = sim_auto.LoadFlowsheet(str(substrate))
        log.log("Flowsheet loaded")

        # Register listener (2-arg, KB §3) ASAP after load
        try:
            sim.AddListener(Action[object, object](log.dwsim_listener))
            log.log("DWSIM 2-arg listener registered")
        except Exception as e:
            log.log(f"AddListener failed (continuing without listener): {e}", level="WARN")

        # Pre-solved state
        try:
            pre_solved = bool(sim.Solved)
        except Exception:
            pre_solved = None
        log.log(f"Pre-solved on load: {pre_solved}")

        # Compounds
        try:
            compound_names = [str(k) for k in sim.SelectedCompounds.Keys]
            log.log(f"Compound count: {len(compound_names)} (first 3: {compound_names[:3]}, last 3: {compound_names[-3:]})")
        except Exception as e:
            log.log(f"Compound enumeration failed: {e}", level="ERROR")
            compound_names = []

        # Property packages
        pp_names = []
        try:
            pp_collection = sim.PropertyPackages
            for pp_id in pp_collection.Keys:
                try:
                    pp = pp_collection[pp_id]
                    pp_names.append({
                        "id": str(pp_id),
                        "name": str(getattr(pp, "ComponentName", "") or getattr(pp, "Name", "") or ""),
                        "type": type(pp).__name__,
                    })
                except Exception:
                    continue
            log.log(f"Property packages found: {len(pp_names)}")
            for pp in pp_names:
                log.log(f"  - {pp}")
        except Exception as e:
            log.log(f"Property package enumeration failed: {e}", level="WARN")

        # ===== Solve =====
        log.log("Calling CalculateFlowsheet4...")
        t0 = time.time()
        errors = sim_auto.CalculateFlowsheet4(sim)
        solve_duration_s = time.time() - t0
        log.log(f"Solve duration: {solve_duration_s:.3f}s")
        try:
            err_list = list(errors) if errors is not None else []
        except Exception:
            err_list = []
        log.log(f"Errors returned: {len(err_list)}")

        try:
            solved = bool(sim.Solved)
        except Exception:
            solved = False

        if not solved:
            err_msg = ""
            try:
                err_msg = str(sim.ErrorMessage)
            except Exception:
                pass
            log.log(f"sim.Solved=False. ErrorMessage: {err_msg}", level="ERROR")
            for i, e in enumerate(err_list[:3]):
                log.log(f"  err[{i}] = {repr(e)[:300]}", level="ERROR")
            write_findings_failure(out_dir, substrate, solve_duration_s,
                                   err_msg, err_list, log)
            log.close()
            sys.exit(2)
        log.log("sim.Solved=True")

        # ===== Inventory walk: object discovery =====
        sim_objects = sim.SimulationObjects
        all_objects = []
        objects_by_class = {}

        for obj_id in sim_objects.Keys:
            try:
                obj = sim_objects[obj_id]
                obj_tag = get_obj_tag(obj)
                obj_type_str = get_obj_type_str(obj)
                internal_name = get_internal_name(obj) or str(obj_id)
                calc = is_calculated(obj)
                pp_name = get_pp_name(obj)
                subsystem = subsystem_from_pp_name(pp_name)
                category = classify_object(obj_type_str)
                prefix = map_objtype_to_prefix(obj_type_str, category)

                rec = {
                    "id": str(obj_id),
                    "internal_name": internal_name,
                    "tag": obj_tag,
                    "object_type": obj_type_str,
                    "category": category,
                    "tag_prefix": prefix,
                    "calculated": calc,
                    "property_package": pp_name,
                    "subsystem": subsystem,
                    "obj_ref": obj,
                }
                all_objects.append(rec)
                objects_by_class.setdefault(category, []).append(rec)
                log.log(f"Object: tag={obj_tag!r}, type={obj_type_str}, "
                        f"category={category}, pp={pp_name}, subsystem={subsystem}, "
                        f"calculated={calc}")
            except Exception as e:
                log.log(f"Object {obj_id} inspection failed: {e}", level="WARN")
                continue

        # ===== Energy stream subsystem trace (Q2) =====
        for rec in objects_by_class.get("energy_stream", []):
            if rec["subsystem"]:
                continue
            traced = derive_energy_subsystem(rec["obj_ref"], all_objects, log)
            if traced is None:
                traced = subsystem_from_name_fallback(rec["tag"])
            rec["subsystem"] = traced
            log.log(f"Energy stream {rec['tag']!r} subsystem (post-trace): {traced}")

        # ===== Inventory walk: per-category extraction =====
        inventory = {
            "meta": {
                "probe_version": "0a-1.0",
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "substrate": str(substrate),
                "solve_duration_s": solve_duration_s,
                "pre_solved_on_load": pre_solved,
                "compound_count": len(compound_names),
                "compound_ids": compound_names,
                "property_packages": pp_names,
                "sim_object_count": len(all_objects),
                "objtype_counts": {
                    cat: len(lst) for cat, lst in objects_by_class.items()
                },
            },
            "objects": [],
        }

        for rec in all_objects:
            inv_obj = {
                "id": rec["id"],
                "internal_name": rec["internal_name"],
                "tag": rec["tag"],
                "object_type": rec["object_type"],
                "category": rec["category"],
                "tag_prefix": rec["tag_prefix"],
                "calculated": rec["calculated"],
                "property_package": rec["property_package"],
                "subsystem": rec["subsystem"],
            }
            cat = rec["category"]
            obj = rec["obj_ref"]
            if cat == "material_stream":
                inv_obj["inventory"] = walk_material_stream(obj, compound_names, log, rec["tag"])
            elif cat == "energy_stream":
                inv_obj["inventory"] = walk_energy_stream(obj, log)
            elif cat == "column":
                inv_obj["inventory"] = {
                    "column_state": walk_column(obj, compound_names, log),
                }
            elif cat in ("heater", "pump", "tank", "recycle", "spec_block"):
                inv_obj["inventory"] = {"properties": introspect_object_properties(obj)}
            else:
                inv_obj["inventory"] = {"properties": introspect_object_properties(obj)}
            inventory["objects"].append(inv_obj)

        # ===== Guards =====
        log.log("Running guards (Bug 4, Bug 6, Bug 8)...")
        guard_results = run_guards(all_objects, compound_names, sim, log)
        inventory["meta"]["guards"] = guard_results
        for k, g in guard_results.items():
            log.log(f"  {k}: {'PASS' if g['passed'] else 'FAIL'}")

        # ===== Build dictionaries =====
        log.log("Building tag/setpoint/constraint dictionaries...")
        tag_dict, setpoint_dict, constraint_dict = build_dictionaries(
            inventory, all_objects, compound_names, log)
        log.log(f"Tag count: {len(tag_dict)}")
        log.log(f"Setpoint count: {len(setpoint_dict)}")
        log.log(f"Constraint count: {len(constraint_dict)}")

        # ===== Ground-truth cross-check =====
        log.log("Cross-checking against architect ground truth...")
        gt = check_ground_truth(inventory, all_objects, log)
        for k, v in gt.items():
            log.log(f"  {k}: expected {v['expected']}, got {v['actual']}, ok={v['ok']}")
        inventory["meta"]["ground_truth_check"] = gt

        # ===== Write outputs =====
        write_json(out_dir / "phase0a_inventory.json",
                   strip_obj_refs(inventory), log)
        write_json(out_dir / "phase0a_tag_dictionary.json", tag_dict, log)
        write_json(out_dir / "phase0a_setpoint_dictionary.json", setpoint_dict, log)
        write_json(out_dir / "phase0a_constraint_dictionary.json", constraint_dict, log)
        write_findings(out_dir, inventory, tag_dict, setpoint_dict, constraint_dict,
                       all_objects, guard_results, log, gt)

        # Tally summary
        log.log("=" * 70)
        log.log("Phase 0a probe complete")
        log.log(f"  Tag count: {len(tag_dict)} (acceptance ≥1200, range [800, 2500])")
        log.log(f"  Setpoint count: {len(setpoint_dict)} (acceptance ≥5)")
        log.log(f"  Constraint count: {len(constraint_dict)} (acceptance =2)")
        log.log(f"  Solve duration: {solve_duration_s:.3f}s")

    except SystemExit:
        raise
    except Exception as e:
        log.log(f"Probe failed: {type(e).__name__}: {e}", level="ERROR")
        log.log(traceback.format_exc(), level="ERROR")
        log.close()
        sys.exit(3)

    log.close()
    sys.exit(0)


if __name__ == "__main__":
    main()
