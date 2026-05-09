# Probe-and-Solve Approach + Streaming Plan

*Comprehensive knowledge transfer for new Claude architect chat*

---

## PART A — The Probe-and-Solve Methodology (Detailed)

### Why this exists

The DWSIM API is large, partially documented, and inconsistent across versions. The C# source is open but understanding it requires reading thousands of lines. Guessing at API calls based on assumptions burns hours and produces broken code. **Probe-and-solve replaces guessing with empirical introspection.**

### The core principle

```
Before writing any code that calls an unfamiliar DWSIM API:
  1. PROBE first — write a small introspection script
  2. INSPECT the output — understand what's actually there
  3. PLAN the call — based on real findings, not assumptions
  4. SOLVE the actual problem — with confidence

Cost: 5-15 minutes for the probe
Benefit: 1-3 hours saved on broken implementation attempts
```

### When to probe

```
PROBE when:
  ✓ Calling a new DWSIM class for the first time
  ✓ Hit an unexpected error class (not simple convergence)
  ✓ Method signature unclear or undocumented
  ✓ Need to know if a property is read-only or writable
  ✓ Need to know what exceptions a method throws
  ✓ Object hierarchy ambiguous (which child of what parent)
  ✓ Need to understand what a returned dict/list contains

DO NOT PROBE when:
  ✗ Already verified pattern (e.g., reading PROP_MS_0 for temperature)
  ✗ Trivial property access on known objects
  ✗ Path is documented in our LEARNINGS.md
```

### Probe script structure (template)

```python
#!/usr/bin/env python3
"""
Phase X probe: <what we're investigating>
Read-only diagnostic. Does NOT modify any artifacts.
"""

import sys
import clr

# Standard DWSIM bootstrap
clr.AddReference('/Applications/DWSIM.app/Contents/MonoBundle/DWSIM.Automation.dll')
clr.AddReference('/Applications/DWSIM.app/Contents/MonoBundle/DWSIM.Interfaces.dll')
clr.AddReference('/Applications/DWSIM.app/Contents/MonoBundle/DWSIM.Thermodynamics.dll')

from DWSIM.Automation import Automation3
from System import Action

# === SECTION 1: API SURFACE INTROSPECTION ===
def introspect_class(cls):
    """Lists public methods and properties of a .NET class."""
    print(f"\n=== {cls.__name__} ===")
    print("PUBLIC METHODS:")
    for method in cls.GetType().GetMethods():
        if method.IsPublic:
            params = [(p.Name, p.ParameterType.Name) for p in method.GetParameters()]
            print(f"  {method.Name}({params}) -> {method.ReturnType.Name}")
    
    print("\nPUBLIC PROPERTIES:")
    for prop in cls.GetType().GetProperties():
        print(f"  {prop.Name}: {prop.PropertyType.Name} "
              f"(R={prop.CanRead}, W={prop.CanWrite})")
    
    print("\nPUBLIC FIELDS:")
    for field in cls.GetType().GetFields():
        if field.IsPublic:
            print(f"  {field.Name}: {field.FieldType.Name}")

# === SECTION 2: LIVE OBJECT INSPECTION ===
def inspect_live_object(obj, name="object"):
    """Inspects an actual instance, not just the class."""
    print(f"\n=== Live {name} ===")
    print(f"Type: {type(obj).__name__}")
    print(f"Repr: {repr(obj)[:200]}")
    
    # Try common DWSIM property accessors
    if hasattr(obj, 'GetType'):
        for method_name in ['GetPropertyValue', 'GetProperties', 'ToString']:
            if hasattr(obj, method_name):
                try:
                    result = getattr(obj, method_name)()
                    print(f"  {method_name}() = {result}")
                except Exception as e:
                    print(f"  {method_name}() raised: {e}")

# === SECTION 3: TOLERANT METHOD EXECUTION ===
def try_method(obj, method_name, *args):
    """Attempts a method call, captures exception class and message."""
    try:
        result = getattr(obj, method_name)(*args)
        print(f"OK: {method_name}({args}) -> {repr(result)[:100]}")
        return result
    except Exception as e:
        print(f"FAIL: {method_name}({args}) raised {type(e).__name__}: {e}")
        return None

# === MAIN PROBE ===
if __name__ == "__main__":
    # Bootstrap
    sim_auto = Automation3()
    sim = sim_auto.LoadFlowsheet(TARGET_FILE)
    
    # Run introspections
    # ...
    
    # Always exit cleanly
    print("\n=== PROBE COMPLETE ===")
    sys.exit(0)
```

### The probe outputs we save

```
For every probe, we save:
  1. The probe script itself        (.py)
  2. The full stdout/stderr log     (_log.txt)
  3. A markdown summary             (_findings.md, sometimes)

Naming convention:
  phase<N><letter>_probe_<topic>.py
  phase<N><letter>_probe_<topic>.log
  phase<N><letter>_probe_findings.md

Examples from our project:
  phase0a_probe_petchar.py + .log
  phase0a_probe_compounds.py + .log
  phase0a_probe_fields.py + .log
  phase2b_diagnosis.md
  phase2d_diagnosis.md
```

### What the probe reports

A good probe report contains:

```
1. WHAT WAS PROBED
   Class names, method names, instance objects examined
   
2. WHAT WAS FOUND
   Public methods and signatures
   Public properties (R/W flags)
   Live property values from real instance
   Exception types raised by failed calls
   
3. WHAT IS BLOCKED
   Private fields (no public setter)
   Methods that throw on common inputs
   Missing API surface
   
4. PROPOSED PATHS FORWARD
   Option A: clean public API (if exists)
   Option B: reflection workaround (if needed)
   Option C: source-read DWSIM to confirm internal pattern
   
5. ARCHITECT DECISION POINT
   "I cannot proceed without your call on A vs B vs C"
```

### Real example — Day 10 Petroleum Characterization probe

```
WHAT WAS PROBED:
  DWSIM.Thermodynamics.Utilities.PetroleumCharacterization.GenerateCompounds
  (Want to programmatically input TBP curve and generate pseudocomponents)

WHAT WAS FOUND:
  - One ctor (no-arg)
  - One callable method: GenerateCompounds(prefix, count, [correlations],
                                           [adjust flags], [bulk scalars])
  - Returns Dictionary
  - Distribution methods exist: DistMW, DistTB, DistSG (all void, no args)
  - Public fields: m_comps (output dict), data (output list)

WHAT IS BLOCKED:
  - dMW, dSG, dTB, _TB, _MW, _SG, q, w, n, T1, T2 — ALL PRIVATE
  - GenerateCompounds() takes scalar bulk values only, NOT curve
  - The UI wizard's curve→pseudocomponent path uses internal/reflection access

PROPOSED PATHS FORWARD:
  Option A: Reflection through private fields (brittle)
  Option B: Riazi.Distr_Riazi from bulk averages only (loses curve fidelity)
  Option C: Source-read DWSIM5 GitHub to find UI wizard call sequence

ARCHITECT DECISION POINT:
  Cannot proceed without choosing A, B, or C.
  
RESULT: We chose to abandon CDU build, use bundled sample instead.
The probe saved us from 4-8 hours of fighting reflection-write code.
```

### Common probe categories

```
1. CLASS DISCOVERY PROBE
   "What classes exist in DWSIM.X.Y namespace?"
   Use: GetTypes(), filter by namespace
   
2. METHOD SIGNATURE PROBE  
   "What methods does class X have, with what parameters?"
   Use: GetType().GetMethods()
   
3. PROPERTY ACCESSIBILITY PROBE
   "Is this property read-only or writable?"
   Use: PropertyInfo.CanWrite
   
4. ENUM/CONSTANT PROBE
   "What are the valid values for an enum parameter?"
   Use: Enum.GetValues(), GetNames()
   
5. LIVE STATE PROBE
   "What's the current state of a running simulation?"
   Use: sim.SimulationObjects, walk the dict
   
6. EXCEPTION PROBE
   "What exception class does method X throw on failure?"
   Use: try/except with type(e).__name__
   
7. SERIALIZATION PROBE
   "Does this property survive a save+load cycle?"
   Use: write, save, drop sim, load, re-read, compare
```

### Probe-then-fix decision tree

```
Encountered new DWSIM API need
              ↓
       Have I done this before?
       ├─ YES → use known pattern
       └─ NO ↓
       
       Is there a single obvious method?
       ├─ YES → try it once, if it fails goto PROBE
       └─ NO ↓
       
       PROBE:
         Write probe script
         Run it
         Inspect output
              ↓
       Does the API exist programmatically?
       ├─ YES → write implementation
       ├─ PARTIAL (private fields) → architect decision
       └─ NO → architect decision (alternative path)
              ↓
       3-attempt cap:
         If implementation fails 3 times after probe,
         STOP and report back to architect
```

---

## PART B — File Selection: Petroleum Distillation with Reboiler Heating Fluid

```
DECISION LOCKED:
  File: Petroleum Distillation with Reboiler Heating Fluid.dwxmz
  Path: /Applications/DWSIM.app/Contents/MonoBundle/samples/
        (or wherever it's installed — verify path)
  Modification: NONE — use as-is
  
WHY THIS FILE OVER THE OTHER:
  - "with Reboiler Heating Fluid" version has MORE unit ops to stream
  - More tags = richer digital twin demo
  - Reboiler heating fluid loop adds energy management complexity
  - Demonstrates heat integration (better portfolio optics)
```

### Phase 0a (revised) — Inspect this specific file

Before writing the streamer, run a targeted probe to know exactly what we're streaming:

```
Probe goal: Inventory the file's complete tag namespace

Probe outputs:
  - Total compound count
  - List of all unit ops (columns, heaters, pumps, mixers, splitters)
  - List of all material streams with their tags
  - List of all energy streams with their tags
  - Property package and solver settings
  - Initial solve attempt (verify it converges on our box)
  - Solve time (informs cycle interval)
```

This is essentially the same probe pattern we ran on the simpler Petroleum Distillation file (Phase 0a Day 10). Should take 10-15 minutes.

---

## PART C — Streaming Architecture (Plan)

### High-level design

```
┌────────────────────────────────────────────────────────────────┐
│  DWSIM Process (long-running Python process)                   │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  Loaded simulation: Petroleum Distillation w/ Reboiler   │ │
│  │  - In-memory after first load                            │ │
│  │  - Stays loaded for life of process                      │ │
│  └──────────────────────────────────────────────────────────┘ │
│                            ↓                                   │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  Solve Loop (every N seconds)                            │ │
│  │  1. Apply pending setpoints (if any)                     │ │
│  │  2. CalculateFlowsheet4(sim)                             │ │
│  │  3. Extract snapshot                                     │ │
│  │  4. Emit to sink(s)                                      │ │
│  │  5. Sleep until next cycle                               │ │
│  └──────────────────────────────────────────────────────────┘ │
│                            ↓                                   │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  Snapshot Emitter (pluggable sinks)                      │ │
│  │  - Local JSON file (always — for debugging)              │ │
│  │  - REST API (for dashboards)                             │ │
│  │  - OPC-UA server (industrial protocol)                   │ │
│  │  - Azure Event Hubs (cloud pipeline)                     │ │
│  └──────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
```

### Module breakdown

```
streamer/
├── __init__.py
├── bootstrap.py       — DWSIM DLL loading, Automation3 setup
├── extractor.py       — Tag extraction logic (the 600+ tag walk)
├── perturbation.py    — Setpoint injection (operator commands)
├── snapshot.py        — Data structure for one solve cycle
├── sinks/
│   ├── __init__.py
│   ├── local_json.py  — File-based output (development)
│   ├── rest_api.py    — FastAPI endpoint
│   ├── opcua.py       — asyncua OPC-UA server
│   └── eventhub.py    — Azure SDK push
├── loop.py            — Main scheduling loop
└── config.py          — Cycle interval, sink selection, etc.

main.py                — Entry point, args parsing, runs loop
```

### Stage 1 implementation (minimal viable streamer)

**Goal:** Local JSON sink only. Prove the loop works. ~4 hours of work.

```python
# loop.py (simplified)
import time
import json
from datetime import datetime
from pathlib import Path

class StreamerLoop:
    def __init__(self, sim_path, sink, cycle_interval=30):
        self.sim_path = sim_path
        self.sink = sink
        self.cycle_interval = cycle_interval
        self.cycle_count = 0
        
        # Load simulation once
        self.sim_auto = Automation3()
        self.sim = self.sim_auto.LoadFlowsheet(sim_path)
        self.sim.AddListener(Action[object, object](self._listener))
        
        # First solve to validate
        self._solve_once()
        if not self.sim.Solved:
            raise RuntimeError(f"Initial solve failed: {self.sim.ErrorMessage}")
    
    def run(self):
        """Main loop — solve, extract, emit, sleep, repeat."""
        while True:
            try:
                cycle_start = time.time()
                
                # Solve
                self._solve_once()
                
                # Extract
                snapshot = self._extract_snapshot()
                snapshot["cycle"] = self.cycle_count
                snapshot["cycle_duration_s"] = time.time() - cycle_start
                
                # Emit
                self.sink.write(snapshot)
                
                # Sleep
                self.cycle_count += 1
                elapsed = time.time() - cycle_start
                sleep_time = max(0, self.cycle_interval - elapsed)
                time.sleep(sleep_time)
                
            except KeyboardInterrupt:
                print("Streamer stopped by user.")
                break
            except Exception as e:
                # Don't crash — log and continue
                print(f"Cycle {self.cycle_count} failed: {e}")
                time.sleep(self.cycle_interval)
    
    def _solve_once(self):
        self.sim_auto.CalculateFlowsheet4(self.sim)
    
    def _extract_snapshot(self):
        # Walk all unit ops and emit tags
        # ... (~620 tag extraction)
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "solved": bool(self.sim.Solved),
            "streams": {...},
            "column": {...},
            "energy": {...},
        }
    
    def _listener(self, msg, level):
        print(f"DWSIM[{level}]: {msg}")
```

### Snapshot data structure

```python
{
    "timestamp": "2026-05-09T14:30:00.000Z",
    "cycle": 142,
    "solved": true,
    "solve_time_s": 3.84,
    "cycle_duration_s": 4.12,
    "errors": [],
    
    "streams": {
        "Oil": {
            "T_K": 350.0,
            "T_C": 76.85,
            "P_Pa": 101325.0,
            "P_bar": 1.013,
            "mass_flow_kg_s": 41.03,
            "mole_flow_mol_s": 500.0,
            "vol_flow_m3_s": 0.0468,
            "vapor_fraction": 0.172,
            "phase": "B",  # B=biphasic, V=vapor, L=liquid
            "compositions": {
                "PSE_3165_27": 0.0344,
                "PSE_3165_24": 0.0343,
                # ... 30 entries
            }
        },
        "Light Product": { ... },
        "Light Intermediate Product": { ... },
        "Intermediate Product": { ... },
        "Heavy Product": { ... }
    },
    
    "columns": {
        "Distillation Column": {
            "tag": "C-101",
            "ic": 15,           # internal iterations
            "ec": 0,            # external iterations
            "rr": 2.499,
            "Q_cond_W": 29756.5,
            "Q_reboil_W": -27282.4,
            "stages": [
                {"i": 0, "T_K": 316.4, "P_Pa": 101325, "V_mol_s": 0, "L_mol_s": 100.0},
                {"i": 1, ...},
                # ... 12 entries
            ]
        }
    },
    
    "energy_streams": {
        "Condenser Duty": 29756.5,
        "Reboiler Duty": -27282.4,
        # ... if reboiler heating fluid file has more
    }
}
```

### Cycle timing strategy

```
Sample solve time: 3.8s on this hardware

Recommended cycle intervals:
  Development:  10-15s   (fast feedback)
  Demo:         30s      (realistic refinery PI rate)
  Production:   60-300s  (typical historian rate)

Why 30s default:
  - Real PI Servers archive at ~1s but compress to ~30s for trends
  - Slow enough to observe changes between cycles
  - Fast enough to look "live" in dashboards
  - Comfortable buffer over solve time (3.8s)
```

### Stages of streaming maturity

```
STAGE 1: Local JSON file sink              ← MVP
  Output: snapshots/snap_<cycle>.json
  Purpose: Prove the loop works
  Effort: 4-6 hours
  
STAGE 2: Append to local JSONL stream
  Output: snapshots.jsonl (one line per cycle)
  Purpose: Bounded file, time-ordered
  Effort: +2 hours
  
STAGE 3: REST API endpoint (FastAPI)
  Output: GET /snapshot, GET /history?from=&to=
  Purpose: Frontend dashboards can pull
  Effort: +6-8 hours
  
STAGE 4: OPC-UA server (asyncua)
  Output: Standard OPC-UA tag tree on tcp://localhost:4840
  Purpose: Industrial protocol credibility
  Effort: +10-15 hours
  
STAGE 5: Azure Event Hubs producer
  Output: Streams to cloud
  Purpose: Triggers Feature 1 → Fabric pipeline
  Effort: +8-12 hours
  
STAGE 6: Bidirectional (setpoints in)
  Input: Operator setpoints from REST/OPC-UA/Event Hubs control queue
  Output: Applied before next solve
  Purpose: Closed-loop digital twin (write-back)
  Effort: +10-15 hours
```

### Key engineering decisions for the new chat

```
Decision 1: Single-process or multi-process?
  Recommendation: SINGLE process for streamer.
  DWSIM Automation3 holds .NET state. Multi-process means re-loading each time.
  Single process keeps simulation in memory across cycles.

Decision 2: Sync or async?
  Recommendation: SYNC for the solve loop, ASYNC for sinks if needed.
  DWSIM solving is blocking. asyncio doesn't help during solve.
  Use threads or asyncio for sink emit if I/O is slow.

Decision 3: Where does the solver run?
  Recommendation: On the operator's Mac (not in cloud).
  DWSIM is a desktop simulator — keep it local.
  Stream OUT to cloud, don't try to host DWSIM in Azure.

Decision 4: How to handle solve failures mid-loop?
  Recommendation: Log it, emit "solved=false" snapshot, continue.
  Don't crash. Don't auto-fix. Let dashboards/agents see the failure state.

Decision 5: How are setpoints applied?
  Recommendation: Pre-solve hook reads pending setpoint queue.
  Validate before applying (out-of-bounds, schema, etc.).
  Apply, solve, snapshot.

Decision 6: Crash recovery?
  Recommendation: Loop wraps in try/except, on any failure save current 
  state and exit cleanly. Systemd or launchd respawns. State is rebuildable.
```

### Anti-patterns specific to streaming

```
✗ Don't reload the simulation every cycle (defeats in-memory caching)
✗ Don't try to multi-thread DWSIM solves (the API is not thread-safe)
✗ Don't stream raw .dwxmz files (binary, large, useless to consumers)
✗ Don't try to stream during solve (locks .NET runtime)
✗ Don't skip the verification block (always check sim.Solved)
✗ Don't emit before extraction completes (partial snapshots are worse than missing)
```

### What success looks like

```
After 1 hour of streamer running:
  ✓ ~120 snapshots written (at 30s interval)
  ✓ Each snapshot has consistent schema
  ✓ Solve time stable (~4s)
  ✓ No crash, no memory leak
  ✓ Logs show steady cycle progression
  ✓ JSON files are loadable as a time series
  ✓ Compositions remain stable (steady-state)
  ✓ Variable changes (T, P, RR) propagate visibly across cycles

This is the foundation. Everything else (Azure, OPC-UA, agents, dashboards)
sits on top of this single proven loop.
```

---

## PART D — What the new architect chat needs to do FIRST

```
Day 11 priorities (in order):

1. INSPECT the chosen file (Phase 0a probe — 15 min)
   - Confirm "Petroleum Distillation with Reboiler Heating Fluid.dwxmz" 
     is at expected path
   - Run inspection probe
   - Document: total tags, unit ops, solve time

2. WRITE the streamer Stage 1 (4-6 hours)
   - Local JSON sink only
   - Single solve loop
   - 30s interval
   - Verify 1 hour of stable streaming

3. ARCHIVE the snapshots (study sample data, 1 hour)
   - Look at 10-20 sample snapshots
   - Confirm tag schema is correct
   - Identify any properties to add/remove

4. PLAN Stage 2-6 progression
   - Decide which sinks matter for demo
   - Get Azure subscription confirmed (if going to Stage 5)
   - Design tag namespace for OPC-UA (if going to Stage 4)

5. SHIP Stage 1 → Stage 2 → Stage 3
   - Get to REST API (Stage 3) before adding cloud
   - Cloud comes when Feature 1 (Data Enablement) starts

Estimated total to Stage 3: 15-20 hours
```

---

## PART E — Critical reminders for the new chat

```
1. The file is locked. Do NOT modify it. Do NOT try to "improve" it.
   "Petroleum Distillation with Reboiler Heating Fluid.dwxmz" 
   is the simulation. It works. Stream it.

2. Probe before assuming. Spend 15 min on a probe to save 3 hours.

3. Single-process streamer. DWSIM Automation3 cannot be multi-process safely.

4. Sample solve time is ~4s. Cycle interval should be 10-30s minimum.

5. Local JSON first, cloud later. Get the loop bulletproof on disk before
   pushing to Azure.

6. Verify-after-write applies to setpoints too. After applying any 
   setpoint, re-read the property to confirm it stuck.

7. The 8 bug classes from LEARNINGS.md still apply. Especially #4 (zombie
   composition) — verify compounds in every snapshot.

8. Read DWSIM_KNOWLEDGE_BASE.md (the document I just gave you) before 
   touching code. Everything in it was learned the hard way.
```

---

*This document plus the DWSIM Knowledge Base from the prior message form the complete handoff. Hand both to the new architect chat as opening context.*
