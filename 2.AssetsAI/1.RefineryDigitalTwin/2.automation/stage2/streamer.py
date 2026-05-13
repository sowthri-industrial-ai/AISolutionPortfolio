#!/usr/bin/env python3
"""Stage 2 streamer: load DWSIM substrate once, solve every 30s, append flat
JSON snapshots to one JSONL file per UTC hour. Rotate at hour boundaries
(close + gzip closed file), retain last N days. Tag-dict-driven extraction
mirrors Stage 1; override rules already baked into the dictionary.

Run: arch -x86_64 ../.venv-x86/bin/python streamer.py"""

import argparse, gzip, json, os, re, shutil, signal, sys, time, traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

SUBSTRATE_PATH = ("/Applications/DWSIM.app/Contents/MonoBundle/samples/"
                  "Petroleum Distillation with Reboiler Heating Fluid.dwxmz")
DWSIM_DLLS = [f"/Applications/DWSIM.app/Contents/MonoBundle/DWSIM.{m}.dll"
              for m in ("Automation", "Interfaces", "Thermodynamics")]
DEFAULT_TAG_DICT = ("/Users/sowthrisomasundaram/Documents/AISolutionPortfolio/"
                    "2.AssetsAI/1.RefineryDigitalTwin/3.probes/phase0a/"
                    "phase0a_tag_dictionary.json")
DEFAULT_OUTPUT_DIR = ("/Users/sowthrisomasundaram/Documents/AISolutionPortfolio/"
                      "2.AssetsAI/1.RefineryDigitalTwin/4.snapshots/stage2")
DEFAULT_INTERVAL_S = 30.0
DEFAULT_RETENTION_DAYS = 1
EXPECTED_TAG_COUNT = 1550
INITIAL_SOLVE_FLAG_S = 10.0
ERROR_CAP = 10
CONSECUTIVE_FAILURE_LIMIT = 3

# PROP_MS_X → phase.Properties field name (Phase 0a-proven). Used only for
# per-phase (VAPOR/LIQUID) thermo on multi-phase streams; OVERALL goes via
# obj.GetPropertyValue() directly.
PROP_MS_PHASE_FIELD = {
    "PROP_MS_0": "temperature", "PROP_MS_1": "pressure", "PROP_MS_2": "massflow",
    "PROP_MS_3": "molarflow", "PROP_MS_4": "volumetric_flow", "PROP_MS_5": "density",
    "PROP_MS_6": "enthalpy", "PROP_MS_7": "entropy", "PROP_MS_8": "molar_enthalpy",
    "PROP_MS_9": "molar_entropy", "PROP_MS_10": "molecularWeight",
}
STAGE_FIELD_MAP = {"T_K": "T", "P_Pa": "P", "V_mol_s": "V", "L_mol_s": "L"}
STAGE_RE = re.compile(r"\.STAGE_(\d+)\.")

# Hour-bucket file naming: stream_YYYY-MM-DDTHH.jsonl[.gz]
HOUR_FORMAT = "%Y-%m-%dT%H"
HOUR_FILE_RE = re.compile(r"^stream_(\d{4}-\d{2}-\d{2}T\d{2})\.jsonl(?:\.gz)?$")

# F3 perturbation inbox — Stage 3 writes one .json file per perturbation
# request here; Stage 2 drains the inbox at the start of each cycle (BEFORE
# CalculateFlowsheet4) so the new value is in effect when DWSIM re-solves.
# Path is overridable via PERTURBATION_INBOX env var; default is sibling
# directory to streamer.py (matches Stage 3's DEFAULT_PERTURBATION_INBOX).
DEFAULT_PERTURBATION_INBOX = (Path(__file__).parent / "perturbations_inbox").as_posix()


def rget(obj, name, default=None):
    """Read a .NET property by name via reflection (bypasses interface masking)."""
    if obj is None:
        return default
    try:
        prop = obj.GetType().GetProperty(name)
        if prop is None or not prop.CanRead:
            return default
        return prop.GetValue(obj, None)
    except Exception:
        return default


def rset(obj, name, value):
    """Write a .NET property via reflection. Returns (ok, error_message).
    Used by the F3 perturbation drainer to apply setpoint changes between
    solve cycles."""
    if obj is None:
        return False, "obj is None"
    try:
        prop = obj.GetType().GetProperty(name)
        if prop is None:
            return False, f"property {name!r} not found on {obj.GetType().Name}"
        if not prop.CanWrite:
            return False, f"property {name!r} is read-only"
        prop.SetValue(obj, value, None)
        return True, None
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# ============================================================================
# F3 — WRITE_STRATEGIES dispatch table
# ============================================================================
#
# The 25 Phase-0a-perturbable setpoints fall into four write-path categories
# (probed live; see 2.automation/f3/probe_setpoint_write.py and
# probe_column_spec_write.py for the diagnostic runs that established this).
#
#   reflection      → rset(obj, name, float(value))
#                     parameter-like properties the solver respects without
#                     recomputing (Pump.Efficiency, Heater.DeltaP, column
#                     tolerances, etc.)
#
#   reflection_int  → rset(obj, name, int(value))
#                     control integers the solver respects (Recycle's
#                     MaximumIterations); Python int → .NET Int32 needs an
#                     explicit cast because pythonnet won't auto-convert
#                     PyInt into Int32 via reflection.
#
#   calc_mode       → rset CalcMode enum first, then rset target value.
#                     Heater inputs are gated by CalcMode; setting OutletT
#                     without first setting CalcMode=OutletTemperature does
#                     write the property field but the solver recomputes it
#                     from HeatDuty + inlet on the next CalculateFlowsheet4.
#                     Params: (enum_int_value,)
#
#   column_spec     → invoke col.SetCondenserSpec / SetReboilerSpec —
#                     DWSIM's official column-spec write API. Updates the
#                     Specs collection atomically (SType + value + units)
#                     so the solver respects the spec.
#                     Params: (side, spec_type_str, units_str)
#                       side ∈ {"C", "R"} (condenser / reboiler)
#                       spec_type_str: "Reflux Ratio" | "Heat Duty" | ...
#                       units_str: "" | "kW" | ...
#
# Universal rule from operator: ALWAYS float() (or int() for the _int
# variant) at the .NET interop boundary. PyInt → .NET Double conversion
# fails silently otherwise (revert through solve as if the write didn't
# happen).
#
# Unmapped (owner_type, property_key) pairs default to "reflection" with
# a "may not persist through solve" audit-trail flag — covers any
# Phase-0a-perturbable property that wasn't categorized here, plus the
# pump-degenerate calc-mode-output properties (OutletTemperature, HeatDuty,
# TemperatureChange) where no CalcMode exists to make them inputs.

WRITE_STRATEGIES: dict = {
    # Strategy A: raw reflection works (parameter-like, not solver-recomputed)
    ("Pump", "Efficiency"):                          ("reflection", None),
    ("Pump", "PressureIncrease"):                    ("reflection", None),
    ("Pump", "DeltaP"):                              ("reflection", None),
    ("Heater", "DeltaP"):                            ("reflection", None),
    ("Heater", "PressureDrop"):                      ("reflection", None),
    ("Heater", "Efficiency"):                        ("reflection", None),
    ("DistillationColumn", "InternalLoopTolerance"): ("reflection", None),
    ("DistillationColumn", "ExternalLoopTolerance"): ("reflection", None),
    ("DistillationColumn", "CondenserDeltaP"):       ("reflection", None),

    # Strategy A_int: integer-typed parameter
    ("Recycle", "MaximumIterations"):                ("reflection_int", None),

    # Strategy C: CalcMode pre-set + write — heater inputs
    # Enum values from operator's first probe: HeatAdded=0, OutletTemperature=1,
    # OutletVaporFraction=3, TemperatureChange=4.
    ("Heater", "OutletTemperature"):                 ("calc_mode", 1),
    ("Heater", "HeatDuty"):                          ("calc_mode", 0),
    ("Heater", "TemperatureChange"):                 ("calc_mode", 4),

    # Strategy D: column spec API — Specs dict keys are "C" / "R"
    ("DistillationColumn", "RefluxRatio"):   ("column_spec", "C", "Reflux Ratio", ""),
    ("DistillationColumn", "CondenserDuty"): ("column_spec", "C", "Heat Duty",    "kW"),
    ("DistillationColumn", "ReboilerDuty"):  ("column_spec", "R", "Heat Duty",    "kW"),

    # Pump degenerate (no CalcMode for these — solver always recomputes).
    # Map explicitly so the audit trail shows we picked "reflection" knowingly
    # rather than falling through the default; persisted_through_solve will
    # be False, the agent sees the regression in the .applied file.
    ("Pump", "OutletTemperature"):                   ("reflection", None),
    ("Pump", "HeatDuty"):                            ("reflection", None),
    ("Pump", "TemperatureChange"):                   ("reflection", None),
}


def _apply_strategy(obj, property_key, value, strategy_name, strategy_params):
    """Dispatch a single write strategy. Returns (ok, error_message).
    Always float()/int() at the .NET boundary per operator's universal rule."""
    if strategy_name == "reflection":
        return rset(obj, property_key, float(value))
    if strategy_name == "reflection_int":
        return rset(obj, property_key, int(value))
    if strategy_name == "calc_mode":
        # Set CalcMode enum first (int value), then write target as float.
        calcmode_int = int(strategy_params[0])
        ok_cm, err_cm = rset(obj, "CalcMode", calcmode_int)
        if not ok_cm:
            # Fallback: use Enum.ToObject + property.SetValue
            try:
                from System import Enum
                cm_prop = obj.GetType().GetProperty("CalcMode")
                cm_type = cm_prop.PropertyType
                if cm_type.IsGenericType and cm_type.Name.startswith("Nullable"):
                    cm_type = cm_type.GetGenericArguments()[0]
                cm_val = Enum.ToObject(cm_type, calcmode_int)
                cm_prop.SetValue(obj, cm_val, None)
            except Exception as e:
                return False, f"CalcMode set failed via rset ({err_cm}) and Enum.ToObject ({type(e).__name__}: {e})"
        return rset(obj, property_key, float(value))
    if strategy_name == "column_spec":
        side, spec_type_str, units_str = strategy_params
        method_name = "SetCondenserSpec" if side == "C" else "SetReboilerSpec"
        try:
            from System import Array, Object
            methods = [m for m in obj.GetType().GetMethods()
                       if str(m.Name) == method_name]
            for m in methods:
                if len(list(m.GetParameters())) == 4:
                    args = Array[Object]([spec_type_str, float(value), units_str, ""])
                    m.Invoke(obj, args)
                    return True, None
            return False, f"no 4-arg {method_name} overload on {obj.GetType().Name}"
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"
    return False, f"unknown strategy {strategy_name!r}"


def coerce(v):
    """Coerce .NET / Python value to JSON-safe primitive. None on NaN/Inf."""
    if v is None or isinstance(v, (bool, str)):
        return v
    if isinstance(v, (int, float)):
        if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))):
            return None
        return v
    try:
        f = float(v)
        return None if (f != f or f in (float("inf"), float("-inf"))) else f
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        return str(v)
    except Exception:
        return None


def hour_floor(dt):
    """Truncate a UTC datetime to the start of its hour."""
    return dt.replace(minute=0, second=0, microsecond=0)


class Streamer:
    def __init__(self, tag_dict_path, output_dir, interval_s, retention_days,
                 perturbation_inbox=None):
        self.tag_dict_path = Path(tag_dict_path).expanduser()
        self.output_dir = Path(output_dir).expanduser()
        self.perturbation_inbox = Path(
            perturbation_inbox or DEFAULT_PERTURBATION_INBOX
        ).expanduser()
        self.interval_s = float(interval_s)
        self.retention_days = int(retention_days)
        self.shutdown = False
        self.cycle = self.consecutive_failures = self.cumulative_tag_errors = 0
        self.log_fp = self.tag_dict = self.sim_auto = self.sim = None
        self.obj_map = {}        # owner_tag → SimulationObject
        self.phase_idx_map = {}  # owner_tag → {OVERALL/VAPOR/LIQUID: int}
        self.current_hour = None
        self.current_file_handle = None
        self.cumulative_perturbations_applied = 0
        self.cumulative_perturbations_failed = 0

    def log(self, msg):
        ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        line = f"[{ts}] {msg}"
        print(line, flush=True)
        if self.log_fp:
            self.log_fp.write(line + "\n")
            self.log_fp.flush()

    def bootstrap(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.perturbation_inbox.mkdir(parents=True, exist_ok=True)
        self.log_fp = open(str(self.output_dir / "streamer.log"), "a", encoding="utf-8")
        self.log("=" * 70)
        self.log(f"Streamer starting PID={os.getpid()} interval={self.interval_s}s "
                 f"retention_days={self.retention_days}")
        self.log(f"  substrate={SUBSTRATE_PATH}")
        self.log(f"  tag_dict={self.tag_dict_path}")
        self.log(f"  output_dir={self.output_dir}")
        self.log(f"  perturbation_inbox={self.perturbation_inbox}")

        if not self.tag_dict_path.is_file():
            self.log(f"FATAL: tag dict not found: {self.tag_dict_path}"); sys.exit(1)
        with open(self.tag_dict_path) as f:
            self.tag_dict = json.load(f)
        n = len(self.tag_dict)
        if n != EXPECTED_TAG_COUNT:
            self.log(f"FATAL: tag dict has {n} entries, expected {EXPECTED_TAG_COUNT};"
                     " substrate or dict has drifted")
            sys.exit(1)
        self.log(f"  tag count:  {n} (sanity gate passed)")

        if not Path(SUBSTRATE_PATH).is_file():
            self.log(f"FATAL: substrate not found: {SUBSTRATE_PATH}"); sys.exit(1)

        import clr
        for dll in DWSIM_DLLS:
            clr.AddReference(dll)
        from DWSIM.Automation import Automation3
        self.sim_auto = Automation3()
        self.log("DWSIM Automation3 instantiated; loading flowsheet...")
        self.sim = self.sim_auto.LoadFlowsheet(SUBSTRATE_PATH)
        self.log("Flowsheet loaded")

        self._build_object_maps()

        self.log("Initial solve (gate)...")
        t0 = time.time()
        self.sim_auto.CalculateFlowsheet4(self.sim)
        dt = time.time() - t0
        self.log(f"Initial solve duration: {dt:.3f}s")
        if dt > INITIAL_SOLVE_FLAG_S:
            self.log(f"WARN: initial solve > {INITIAL_SOLVE_FLAG_S}s; investigate")
        if not bool(self.sim.Solved):
            err = ""
            try: err = str(self.sim.ErrorMessage)
            except Exception: pass
            self.log(f"FATAL: initial solve failed: {err}"); sys.exit(2)

        # Open current hour's file, run startup retention sweep (Phase 2 specifics).
        # Per architect Q1: leave any orphaned prior-hour .jsonl uncompressed —
        # retention sweep handles them when old enough.
        self.current_hour = hour_floor(datetime.now(timezone.utc))
        self.current_file_handle = self._open_hour_file(self.current_hour)
        kept, deleted = self._retention_sweep()
        self.log(f"Active file: {self._file_for_hour(self.current_hour).name}; "
                 f"startup retention sweep: kept {kept}, deleted {deleted}")
        self.log("Initial solve OK; entering main loop")

    def _build_object_maps(self):
        for obj_id in self.sim.SimulationObjects.Keys:
            obj = self.sim.SimulationObjects[obj_id]
            try:
                go = obj.GraphicObject
                tag = str(go.Tag) if go is not None else ""
            except Exception:
                tag = ""
            if not tag:
                continue
            self.obj_map[tag] = obj
            try:
                if obj.GetType().Name == "MaterialStream":
                    phases = rget(obj, "Phases")
                    if phases is not None:
                        self.phase_idx_map[tag] = self._classify_phases(phases)
            except Exception:
                pass
        self.log(f"Object map: {len(self.obj_map)} entries; "
                 f"phase maps for {len(self.phase_idx_map)} streams")

    def _classify_phases(self, phases_dict):
        """OVERALL/VAPOR/LIQUID phase indices (bilingual EN+PT name match)."""
        out = {}
        try: keys = list(phases_dict.Keys)
        except Exception: return out
        for k in keys:
            try:
                idx = int(k)
                name = (str(rget(phases_dict[k], "Name") or "")).lower()
            except Exception:
                continue
            if idx == 0:
                out.setdefault("OVERALL", idx)
            elif "vapor" in name or "vapour" in name:
                out.setdefault("VAPOR", idx)
            elif name.startswith("liquid") or name.startswith("líquido"):
                out.setdefault("LIQUID", idx)
        return out

    # Extraction logic verbatim from Stage 1 — same dispatch on owner_type.
    def _extract_one(self, entry):
        """Return (value, error_msg). error_msg is None on success."""
        owner_tag = entry["owner_tag"]
        owner_type = entry["owner_type"]
        property_key = entry["property_key"]
        obj = self.obj_map.get(owner_tag)
        if obj is None:
            return None, f"owner_tag not in sim: {owner_tag!r}"
        try:
            if owner_type == "MaterialStream":
                return self._extract_ms(obj, owner_tag, entry.get("phase"), property_key), None
            if owner_type == "DistillationColumn":
                return self._extract_column(obj, property_key, entry["tag_id"]), None
            # EnergyStream + Heater + Pump + Tank + Recycle: reflection on key
            return coerce(rget(obj, property_key)), None
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"

    def _extract_ms(self, obj, owner_tag, phase, property_key):
        if property_key.startswith(("MoleFraction.", "MassFraction.")):
            kind, compound = property_key.split(".", 1)
            phases = rget(obj, "Phases")
            phase_obj = phases[self._resolve_phase_idx(owner_tag, phase)] if phases else None
            compounds = rget(phase_obj, "Compounds") if phase_obj else None
            if compounds is None:
                return None
            cmp = compounds[compound]
            return coerce(getattr(cmp, kind, None) if getattr(cmp, kind, None) is not None
                          else rget(cmp, kind))
        if property_key.startswith("PROP_MS_"):
            if phase in (None, "OVERALL"):
                return coerce(obj.GetPropertyValue(property_key))
            field = PROP_MS_PHASE_FIELD.get(property_key)
            phases = rget(obj, "Phases")
            if not field or phases is None:
                return None
            props = rget(phases[self._resolve_phase_idx(owner_tag, phase)], "Properties")
            return coerce(getattr(props, field, None)) if props is not None else None
        return coerce(rget(obj, property_key))

    def _resolve_phase_idx(self, owner_tag, phase):
        m = self.phase_idx_map.get(owner_tag, {})
        return m.get("OVERALL", 0) if phase in (None, "OVERALL") else m.get(phase, 0)

    def _extract_column(self, col, property_key, tag_id):
        m = STAGE_RE.search(tag_id)
        if not m:
            return coerce(rget(col, property_key))
        stages = rget(col, "Stages")
        if stages is None:
            return None
        stage = stages[int(m.group(1))]
        if property_key.startswith("LiqMoleFraction."):
            compound = property_key.split(".", 1)[1]
            for attr in ("xc", "LiqCompositions", "Compositions"):
                d = getattr(stage, attr, None) or rget(stage, attr)
                if d is None:
                    continue
                try: return coerce(d[compound])
                except Exception: continue
            return None
        f = STAGE_FIELD_MAP.get(property_key, property_key)
        v = getattr(stage, f, None)
        return coerce(v if v is not None else rget(stage, f))

    # Hour-bucket file management (Stage 2 specific).
    def _file_for_hour(self, hour_dt):
        return self.output_dir / f"stream_{hour_dt.strftime(HOUR_FORMAT)}.jsonl"

    def _open_hour_file(self, hour_dt):
        """Open the hour-bucket .jsonl in append mode. Restart-in-same-hour
        appends rather than truncates."""
        return open(str(self._file_for_hour(hour_dt)), "a", encoding="utf-8")

    def _gzip_file(self, jsonl_path):
        """Compress jsonl → jsonl.gz, delete original. On failure: log warn,
        leave orphan .jsonl, best-effort cleanup partial .gz, return False."""
        gz_path = jsonl_path.with_suffix(jsonl_path.suffix + ".gz")
        try:
            with open(str(jsonl_path), "rb") as src, gzip.open(str(gz_path), "wb") as dst:
                shutil.copyfileobj(src, dst)
            jsonl_path.unlink()
            return True
        except Exception as e:
            self.log(f"WARN: gzip failed for {jsonl_path.name}: "
                     f"{type(e).__name__}: {e}; leaving uncompressed orphan")
            try: gz_path.unlink()
            except Exception: pass
            return False

    def _retention_sweep(self):
        """Delete hour-bucket files whose hour is older than the retention
        window. Threshold semantics: file_hour < (now_hour - 24h * retention_days).
        At steady state with retention_days=1, exactly 24 buckets remain."""
        now_hour = hour_floor(datetime.now(timezone.utc))
        threshold = now_hour - timedelta(hours=24 * self.retention_days)
        kept = 0
        deleted = 0
        for f in self.output_dir.glob("stream_*.jsonl*"):
            m = HOUR_FILE_RE.match(f.name)
            if not m:
                continue
            try:
                file_hour = datetime.strptime(m.group(1), HOUR_FORMAT).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if file_hour < threshold:
                try:
                    f.unlink()
                    deleted += 1
                except Exception as e:
                    self.log(f"WARN: retention delete failed for {f.name}: {e}")
            else:
                kept += 1
        return kept, deleted

    # F3 perturbation inbox — Stage 3's POST /setpoints/{id}/value writes one
    # JSON request per file here. We drain at the start of each cycle BEFORE
    # CalculateFlowsheet4 so the new setpoint is in effect when DWSIM re-solves.
    # Failed writes archive immediately as .failed; successful writes defer
    # archive to _finalize_perturbations() which reads back AFTER solve and
    # records persisted_through_solve so reverts surface in the audit trail.
    def _drain_perturbation_inbox(self):
        """Apply writes for all pending *.json requests. Returns list of
        deferred entries that need post-solve verify + archive — each item:
            {"src_path": Path, "req": dict, "result": dict}
        Failed writes (strategy invocation errored) are archived inline as
        .failed; not included in the returned deferred list."""
        if not self.perturbation_inbox.is_dir():
            return []
        # Glob *.json catches pending only; .json.tmp / .applied / .failed
        # have different suffixes.
        pending = sorted(
            p for p in self.perturbation_inbox.glob("*.json")
            if not p.name.endswith(".json.tmp")
        )
        deferred: list[dict] = []
        for path in pending:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    req = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                self.log(f"WARN: malformed perturbation file {path.name}: {e}",
                         level="WARN")
                continue
            result = self._apply_perturbation(req)
            if result.get("status") == "applied":
                # Defer archive until after this cycle's solve so we can record
                # post-solve persistence.
                deferred.append({"src_path": path, "req": req, "result": result})
            else:
                # Write itself failed (strategy errored). Archive inline.
                self._archive_perturbation(path, req, result)
        return deferred

    def _apply_perturbation(self, req):
        """Look up strategy in WRITE_STRATEGIES, apply write. Returns a result
        dict with status=applied|failed + strategy_used + diagnostic fields.
        Post-solve persistence is recorded later by _finalize_perturbations().
        """
        owner_tag = req.get("owner_tag")
        owner_type = req.get("owner_type")
        property_key = req.get("property_key")
        value = req.get("value")
        obj = self.obj_map.get(owner_tag)
        ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
            "+00:00", "Z"
        )
        if obj is None:
            self.cumulative_perturbations_failed += 1
            self.log(f"perturbation FAILED setpoint={req.get('setpoint_id')} "
                     f"reason=owner_not_in_sim", level="ERROR")
            return {
                "status": "failed",
                "cycle": self.cycle,
                "applied_at": ts,
                "strategy_used": None,
                "error": f"owner_tag not in sim: {owner_tag!r}",
            }

        # Dispatch
        strategy_tuple = WRITE_STRATEGIES.get((owner_type, property_key))
        if strategy_tuple is None:
            # Unmapped — default to plain reflection with a flag so the audit
            # surfaces "may not persist".
            strategy_name = "reflection"
            strategy_params = None
            strategy_unmapped = True
        else:
            strategy_name = strategy_tuple[0]
            strategy_params = strategy_tuple[1:] if len(strategy_tuple) > 1 else (None,)
            # Normalize: ("reflection", None) → params=(None,); collapse to None
            # for the audit field when there's nothing meaningful to record.
            if strategy_params == (None,):
                strategy_params = None
            strategy_unmapped = False

        prev_value = coerce(rget(obj, property_key))
        ok, err = _apply_strategy(obj, property_key, value, strategy_name,
                                   strategy_params)
        if not ok:
            self.cumulative_perturbations_failed += 1
            self.log(f"perturbation FAILED setpoint={req.get('setpoint_id')} "
                     f"strategy={strategy_name} value={value} reason={err}",
                     level="ERROR")
            return {
                "status": "failed",
                "cycle": self.cycle,
                "applied_at": ts,
                "prev_value": prev_value,
                "attempted_value": value,
                "strategy_used": strategy_name,
                "strategy_params": list(strategy_params) if strategy_params else None,
                "strategy_unmapped": strategy_unmapped,
                "error": err,
            }

        # Immediate (pre-solve) verify-after-write — KB §3 catches obvious
        # serialization mangling. Post-solve verify happens in
        # _finalize_perturbations() once this cycle's CalculateFlowsheet4
        # completes.
        immediate_value = coerce(rget(obj, property_key))
        return {
            "status": "applied",
            "cycle": self.cycle,
            "applied_at": ts,
            "prev_value": prev_value,
            "immediate_value": immediate_value,
            "strategy_used": strategy_name,
            "strategy_params": list(strategy_params) if strategy_params else None,
            "strategy_unmapped": strategy_unmapped,
        }

    def _finalize_perturbations(self, deferred):
        """After the cycle's CalculateFlowsheet4, read each perturbed
        property's post-solve value, compute persisted_through_solve, and
        archive the merged (req + result) as <uuid>.applied. Returns a list
        of {setpoint_id, status, persisted_through_solve} dicts for the
        snapshot's per-cycle summary."""
        summary = []
        for entry in deferred:
            src_path = entry["src_path"]
            req = entry["req"]
            result = entry["result"]
            obj = self.obj_map.get(req.get("owner_tag"))
            property_key = req.get("property_key")
            target = None
            try:
                target = float(req.get("value"))
            except (TypeError, ValueError):
                target = None

            post_solve = coerce(rget(obj, property_key)) if obj is not None else None
            result["new_value"] = post_solve

            # Persistence: within max(1% of |target|, 0.001) absolute tolerance.
            persisted = False
            if isinstance(post_solve, (int, float)) and target is not None:
                tol = max(abs(target) * 0.01, 0.001)
                persisted = abs(post_solve - target) <= tol
            result["persisted_through_solve"] = persisted

            self.cumulative_perturbations_applied += 1
            if persisted:
                self.log(
                    f"perturbation APPLIED setpoint={req.get('setpoint_id')} "
                    f"strategy={result.get('strategy_used')} "
                    f"prev={result.get('prev_value')} → post-solve={post_solve}"
                )
            else:
                self.log(
                    f"perturbation APPLIED-BUT-REVERTED "
                    f"setpoint={req.get('setpoint_id')} "
                    f"strategy={result.get('strategy_used')} "
                    f"target={target} post-solve={post_solve} "
                    f"(solver did not respect write)",
                    level="WARN",
                )

            self._archive_perturbation(src_path, req, result)
            summary.append({
                "setpoint_id": req.get("setpoint_id"),
                "status": "applied",
                "persisted_through_solve": persisted,
                "strategy_used": result.get("strategy_used"),
            })
        return summary

    def _archive_perturbation(self, src_path, req, result):
        """Write merged (req + result) to <request_id>.<applied|failed> via
        atomic tmp+rename, then delete the original .json file."""
        request_id = req.get("request_id") or src_path.stem
        suffix = ".applied" if result.get("status") == "applied" else ".failed"
        merged = dict(req)
        merged.update(result)
        target = self.perturbation_inbox / f"{request_id}{suffix}"
        tmp = self.perturbation_inbox / f"{request_id}{suffix}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(merged, f, indent=2, ensure_ascii=False)
            os.rename(tmp, target)
        except OSError as e:
            self.log(f"WARN: archive write failed for {request_id}: {e}",
                     level="WARN")
            return
        try:
            src_path.unlink()
        except OSError:
            pass

    def _rotate_to(self, new_hour):
        """Close current handle, gzip closed file, open new, run retention sweep."""
        old_hour = self.current_hour
        old_path = self._file_for_hour(old_hour)
        try:
            self.current_file_handle.close()
        except Exception:
            pass
        gz_ok = self._gzip_file(old_path)
        self.current_hour = new_hour
        self.current_file_handle = self._open_hour_file(new_hour)
        kept, deleted = self._retention_sweep()
        archived = f"{old_path.name}.gz" if gz_ok else f"{old_path.name} (orphan)"
        self.log(f"Rotated to {self._file_for_hour(new_hour).name}, "
                 f"archived {archived}, retention sweep: kept {kept}, deleted {deleted}")

    def run_cycle(self):
        t0 = time.time()
        ts = datetime.now(timezone.utc)
        ts_iso = ts.isoformat(timespec="milliseconds").replace("+00:00", "Z")

        # F3: drain perturbation inbox BEFORE solve so the new setpoint is
        # in effect when DWSIM recomputes. The drain APPLIES the writes via
        # WRITE_STRATEGIES dispatch but DEFERS archiving; post-solve verify
        # + .applied archive happens after CalculateFlowsheet4 below in
        # _finalize_perturbations(). Failures here are logged but never
        # block the solve.
        deferred_perturbations = []
        try:
            deferred_perturbations = self._drain_perturbation_inbox()
        except Exception as e:
            # Defensive: any unhandled error in the drain path is logged
            # and swallowed.
            self.log(f"WARN: perturbation drain raised "
                     f"{type(e).__name__}: {e}", level="WARN")

        snapshot = {"timestamp": ts_iso, "cycle": self.cycle, "solved": False,
                    "solve_time_s": None, "cycle_duration_s": None,
                    "tag_count": 0, "errors": [], "tags": {},
                    "perturbations_applied_this_cycle": []}
        try:
            t_solve = time.time()
            self.sim_auto.CalculateFlowsheet4(self.sim)
            snapshot["solve_time_s"] = round(time.time() - t_solve, 3)
            sim_solved = bool(self.sim.Solved)
            snapshot["solved"] = sim_solved

            # F3: post-solve verify + archive each deferred perturbation. Even
            # if sim.Solved is False, we still finalize — the audit trail
            # should record whatever the post-solve read says about the
            # property (potentially with persisted_through_solve=False).
            if deferred_perturbations:
                try:
                    snapshot["perturbations_applied_this_cycle"] = (
                        self._finalize_perturbations(deferred_perturbations)
                    )
                except Exception as e:
                    self.log(f"WARN: perturbation finalize raised "
                             f"{type(e).__name__}: {e}", level="WARN")

            if sim_solved:
                tags, errors, total_err = {}, [], 0
                for entry in self.tag_dict:
                    value, err = self._extract_one(entry)
                    if err is not None:
                        total_err += 1
                        if len(errors) < ERROR_CAP:
                            errors.append(f"{entry['tag_id']}: {err}")
                        continue
                    tags[entry["tag_id"]] = value
                snapshot.update(tags=tags, tag_count=len(tags), errors=errors)
                if total_err > ERROR_CAP:
                    snapshot["errors_truncated"] = True
                    snapshot["total_error_count"] = total_err
                self.cumulative_tag_errors += total_err
                self.consecutive_failures = 0
            else:
                try: err = str(self.sim.ErrorMessage)
                except Exception: err = ""
                snapshot["errors"] = [f"sim.Solved=False: {err}"]
                self.consecutive_failures += 1
        except Exception as e:
            snapshot.update({"solved": False, "solve_time_s": None, "tag_count": 0,
                             "tags": {}, "errors": [f"{type(e).__name__}: {e}"]})
            self.consecutive_failures += 1
            self.log(f"Cycle {self.cycle} caught {type(e).__name__}: {e}")
            # Solve crashed before finalize ran. Finalize anyway so the
            # perturbation audit trail doesn't get stuck — post-solve reads
            # may show stale or partial values, but persisted_through_solve
            # will correctly report False if so.
            if deferred_perturbations:
                try:
                    snapshot["perturbations_applied_this_cycle"] = (
                        self._finalize_perturbations(deferred_perturbations)
                    )
                except Exception as fe:
                    self.log(f"WARN: perturbation finalize raised (post-crash) "
                             f"{type(fe).__name__}: {fe}", level="WARN")

        snapshot["cycle_duration_s"] = round(time.time() - t0, 3)

        # Rotate if we've crossed an hour boundary since the last write.
        new_hour = hour_floor(datetime.now(timezone.utc))
        if new_hour != self.current_hour:
            self._rotate_to(new_hour)

        # Atomic JSONL line: compact JSON + newline + flush so tail -f sees it.
        line = json.dumps(snapshot, separators=(",", ":"), ensure_ascii=False)
        self.current_file_handle.write(line + "\n")
        self.current_file_handle.flush()

        err_n = snapshot.get("total_error_count", len(snapshot["errors"]))
        self.log(f"cycle={self.cycle} solved={'true' if snapshot['solved'] else 'false'} "
                 f"tags={snapshot['tag_count']}/{len(self.tag_dict)} "
                 f"errors={err_n} duration={snapshot['cycle_duration_s']}s")

    def run(self):
        self.bootstrap()
        start_ts = time.time()
        try:
            while not self.shutdown:
                cycle_start = time.time()
                self.run_cycle()
                if self.consecutive_failures >= CONSECUTIVE_FAILURE_LIMIT:
                    self.log(f"FATAL: {self.consecutive_failures} consecutive cycle "
                             f"failures; exiting non-zero (structural problem)")
                    sys.exit(2)
                self.cycle += 1
                deadline = cycle_start + self.interval_s
                while not self.shutdown and time.time() < deadline:
                    time.sleep(min(0.5, max(0.0, deadline - time.time())))
        except SystemExit:
            raise
        except Exception as e:
            self.log(f"FATAL unhandled: {type(e).__name__}: {e}")
            self.log(traceback.format_exc())
            sys.exit(3)
        finally:
            duration = time.time() - start_ts
            # Close active file handle but DO NOT gzip — restart-in-same-hour
            # appends to the existing .jsonl per briefing point 7.
            if self.current_file_handle is not None:
                try: self.current_file_handle.close()
                except Exception: pass
            self.log(f"Streamer stopped after {self.cycle} cycles ({duration:.1f}s), "
                     f"{self.cumulative_tag_errors} cumulative tag errors, "
                     f"{self.cumulative_perturbations_applied} perturbations applied, "
                     f"{self.cumulative_perturbations_failed} perturbations failed")
            if self.log_fp:
                self.log_fp.flush()
                self.log_fp.close()


def main():
    p = argparse.ArgumentParser(description="Stage 2 JSONL streamer with hourly rotation")
    p.add_argument("--tag-dict", default=DEFAULT_TAG_DICT)
    p.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    p.add_argument("--interval", type=float, default=DEFAULT_INTERVAL_S,
                   help="Cycle interval in seconds (default 30)")
    p.add_argument("--retention-days", type=int, default=DEFAULT_RETENTION_DAYS,
                   help="Days of hour-bucket files to retain (default 1)")
    p.add_argument("--perturbation-inbox",
                   default=os.environ.get("PERTURBATION_INBOX") or DEFAULT_PERTURBATION_INBOX,
                   help="Stage 2 perturbation inbox dir (F3 setpoint writes from Stage 3)")
    args = p.parse_args()
    s = Streamer(args.tag_dict, args.output_dir, args.interval, args.retention_days,
                 perturbation_inbox=args.perturbation_inbox)
    def _sig(signum, _frame):
        s.log(f"Received signal {signum}; shutdown after current cycle"); s.shutdown = True
    signal.signal(signal.SIGINT, _sig); signal.signal(signal.SIGTERM, _sig)
    s.run(); sys.exit(0)


if __name__ == "__main__":
    main()
