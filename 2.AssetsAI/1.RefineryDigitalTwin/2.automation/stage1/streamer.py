#!/usr/bin/env python3
"""Stage 1 streamer: load DWSIM substrate once, solve every 30s, emit flat JSON
snapshot per cycle. Tag-dict-driven. Run: arch -x86_64 ../.venv-x86/bin/python streamer.py"""

import argparse, json, os, re, signal, sys, time, traceback
from datetime import datetime, timezone
from pathlib import Path

SUBSTRATE_PATH = ("/Applications/DWSIM.app/Contents/MonoBundle/samples/"
                  "Petroleum Distillation with Reboiler Heating Fluid.dwxmz")
DWSIM_DLLS = [f"/Applications/DWSIM.app/Contents/MonoBundle/DWSIM.{m}.dll"
              for m in ("Automation", "Interfaces", "Thermodynamics")]
DEFAULT_TAG_DICT = ("/Users/sowthrisomasundaram/Documents/AISolutionPortfolio/"
                    "2.AssetsAI/1.RefineryDigitalTwin/3.probes/phase0a/"
                    "phase0a_tag_dictionary.json")
DEFAULT_OUTPUT_DIR = ("/Users/sowthrisomasundaram/Documents/AISolutionPortfolio/"
                      "2.AssetsAI/1.RefineryDigitalTwin/4.snapshots/stage1")
DEFAULT_INTERVAL_S = 30.0
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


class Streamer:
    def __init__(self, tag_dict_path, output_dir, interval_s):
        self.tag_dict_path = Path(tag_dict_path).expanduser()
        self.output_dir = Path(output_dir).expanduser()
        self.interval_s = float(interval_s)
        self.shutdown = False
        self.cycle = self.consecutive_failures = self.cumulative_tag_errors = 0
        self.log_fp = self.tag_dict = self.sim_auto = self.sim = None
        self.obj_map = {}        # owner_tag → SimulationObject
        self.phase_idx_map = {}  # owner_tag → {OVERALL/VAPOR/LIQUID: int}

    def log(self, msg):
        ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        line = f"[{ts}] {msg}"
        print(line, flush=True)
        if self.log_fp:
            self.log_fp.write(line + "\n")
            self.log_fp.flush()

    def bootstrap(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.log_fp = open(str(self.output_dir / "streamer.log"), "a", encoding="utf-8")
        self.log("=" * 70)
        self.log(f"Streamer starting PID={os.getpid()} interval={self.interval_s}s")
        self.log(f"  substrate={SUBSTRATE_PATH}")
        self.log(f"  tag_dict={self.tag_dict_path}")
        self.log(f"  output_dir={self.output_dir}")

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
        # Composition: MoleFraction.<C> / MassFraction.<C>
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
        # Thermo: PROP_MS_*. OVERALL/single via direct GetPropertyValue (on interface);
        # VAPOR/LIQUID via phase.Properties.<field> (PROP_MS_PHASE_FIELD map).
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

    def run_cycle(self):
        t0 = time.time()
        ts = datetime.now(timezone.utc)
        ts_iso = ts.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        ts_fname = ts.strftime("%Y-%m-%dT%H-%M-%SZ")

        snapshot = {"timestamp": ts_iso, "cycle": self.cycle, "solved": False,
                    "solve_time_s": None, "cycle_duration_s": None,
                    "tag_count": 0, "errors": [], "tags": {}}
        try:
            t_solve = time.time()
            self.sim_auto.CalculateFlowsheet4(self.sim)
            snapshot["solve_time_s"] = round(time.time() - t_solve, 3)
            sim_solved = bool(self.sim.Solved)
            snapshot["solved"] = sim_solved

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

        snapshot["cycle_duration_s"] = round(time.time() - t0, 3)

        # Atomic write
        path = self.output_dir / f"snap_{ts_fname}.json"
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False)
        os.rename(tmp, path)

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
            self.log(f"Streamer stopped after {self.cycle} cycles ({duration:.1f}s), "
                     f"{self.cumulative_tag_errors} cumulative tag errors")
            if self.log_fp:
                self.log_fp.flush()
                self.log_fp.close()


def main():
    p = argparse.ArgumentParser(description="Stage 1 local JSON streamer")
    p.add_argument("--tag-dict", default=DEFAULT_TAG_DICT)
    p.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    p.add_argument("--interval", type=float, default=DEFAULT_INTERVAL_S)
    args = p.parse_args()
    s = Streamer(args.tag_dict, args.output_dir, args.interval)
    def _sig(signum, _frame):
        s.log(f"Received signal {signum}; shutdown after current cycle"); s.shutdown = True
    signal.signal(signal.SIGINT, _sig); signal.signal(signal.SIGTERM, _sig)
    s.run(); sys.exit(0)

if __name__ == "__main__":
    main()
