# DWSIM Programmatic Knowledge Base

Distilled from 10 days of building, debugging, and probing DWSIM 9.0.5 on macOS Sequoia (Apple Silicon, Mono x86_64). For new Claude chat architecting refinery digital twin work.

## 1. Toolchain (proven working)

```
Platform:       macOS Sequoia, Apple Silicon (M-series)
DWSIM:          9.0.5 (installed at /Applications/DWSIM.app/)
Mono:           x86_64 via Rosetta 2 (REQUIRED — DWSIM binaries are .NET Framework, not .NET Core)
Python:         3.11+ in Rosetta venv
pythonnet:      3.0.5 (NOT 3.0.4 — has macOS bugs)
Permissions:    macOS Full Disk Access granted to Terminal app
Run pattern:    arch -x86_64 .venv-x86/bin/python <script>.py
```

Critical setup gotchas:

- DWSIM Mac build is x86_64-only. Native ARM Python won't load DWSIM DLLs.
- Without Full Disk Access, DWSIM can read but cannot save .dwxmz files (silent fail).
- `pythonnet` must be 3.0.5+ for `clr.AddReference()` to find Mono assemblies on macOS.
- DLLs live at `/Applications/DWSIM.app/Contents/MonoBundle/`, NOT `/Resources/`.

## 2. The Automation API (the only viable programmatic path)

```python
# Bootstrap pattern (works every time)
import clr
clr.AddReference('/Applications/DWSIM.app/Contents/MonoBundle/DWSIM.Automation.dll')
clr.AddReference('/Applications/DWSIM.app/Contents/MonoBundle/DWSIM.Interfaces.dll')
clr.AddReference('/Applications/DWSIM.app/Contents/MonoBundle/DWSIM.Thermodynamics.dll')

from DWSIM.Automation import Automation3
sim_auto = Automation3()

# Two entry points:
sim = sim_auto.CreateFlowsheet()           # clean build (preferred)
sim = sim_auto.LoadFlowsheet(path)         # load existing .dwxmz
```

Why Automation3 (not Automation2): Automation3 is the actively maintained class. Automation2 exists but has fewer methods and unclear deprecation status.

Saving: `sim_auto.SaveFlowsheet(sim, path, True)` — third arg True = compressed .dwxmz format.

## 3. Solving — the Wang-Henke pattern that works

```python
from System import Action

# The 2-arg MessageListener pattern (DO NOT use 1-arg version)
def listener(msg, level):
    print(f"DWSIM> [{level}] {msg}")

sim.AddListener(Action[object, object](listener))

# Solve via CalculateFlowsheet4 (NOT CalculateFlowsheet)
errors = sim_auto.CalculateFlowsheet4(sim)

# Verify convergence
if sim.Solved:
    print("Converged")
else:
    print(f"Failed: {sim.ErrorMessage}")
```

Solver gotchas:

- `CalculateFlowsheet4` returns a list of exceptions, not a status code.
- `sim.Solved` is the truth. Always check it after solving.
- Wang-Henke convergence is the default for Distillation columns and works for most cases.
- Tolerances: 1e-4 internal / 1e-3 external are the proven defaults.

## 4. The 8 bug classes we documented (not theoretical — we hit them)

### Bug Class 1: Stale tolerance state-leak
Loading a saved flowsheet may carry forward tolerance settings from prior solves. Always set tolerances explicitly after load, before next solve.

### Bug Class 2: Silent StageNumber=0 on SetReboilerSpec
`SetReboilerSpec()` defaults `StageNumber` to 0 if not passed. Stage 0 is the condenser. Always pass StageNumber explicitly = (NumberOfStages - 1).

### Bug Class 3: SpecUnit "W" → "Mass" mangling
Setting `Heat_Duty` SpecUnit as "W" can get internally mangled to "Mass" during serialization. Use Watts numerical values but verify SpecUnit after write via re-read.

### Bug Class 4: Zombie composition (silent failure)
If you add compounds to a flowsheet AFTER creating a material stream, the stream's composition dict isn't auto-updated. Stream may show 0 mole fraction for all compounds while solver claims "converged." Verify compound count in EVERY material stream after add.

### Bug Class 5: Equimolar bundle convergence fail
Adding 5 compounds to a flowsheet, then jumping to 20 compounds, fails. The proven path: 5 → 6 → 7 → ... → 20, one at a time, with a solve verification between each. We call this "atomic ladder." Treat as required for any complex slate.

### Bug Class 6: False convergence
`sim.Solved == True` but distillate composition is garbage. Always verify BOTH distillate AND bottoms compositions after solve, not just the convergence flag.

### Bug Class 7: InterExchanger MaterialStream cast bug (CDU-specific)
At line 2898 of DWSIM source, casting an InterExchanger stream to MaterialStream throws InvalidCastException. Workaround: use EnergyStream for all pumparound duties, never MaterialStream-based InterExchangers.

### Bug Class 8: Stages.Count vs NumberOfStages mismatch (CDU-specific)
`column.NumberOfStages` and `column.Stages.Count` can disagree after structural mutations. The `Stages` collection can have orphan entries. Validate parity before solving any modified column.

## 5. The Petroleum Characterization API limitation (today's blocker)

This is the most strategically important finding from Day 10:

```
Class: DWSIM.Thermodynamics.Utilities.PetroleumCharacterization.GenerateCompounds

Public surface:
  - One ctor (no-arg)
  - One method: GenerateCompounds(prefix, count, [correlation strings],
                                  [adjust flags], [scalar bulk values])
                returning Dictionary

Critical limitation:
  Every CURVE-INPUT field (dMW, dSG, dTB, _TB, _MW, _SG, q, w, n, T1, T2)
  is PRIVATE. No public setters. No property bag.
  GenerateCompounds(...) takes scalar bulk values only — NOT a TBP curve.
```

Implication: The DWSIM UI's Petroleum Characterization Wizard (which DOES accept TBP curves) uses reflection or an internal API path that is not publicly exposed. Three options exist:

- A: Reflection-write to private fields (works, but tied to internal field names)
- B: Use `Riazi.Distr_Riazi(n, MW, SG, WK, T1, T2, V1, V2)` — bulk-only, no curve fidelity
- C: Read DWSIM source on GitHub to find exact wizard implementation

For digital twin work, this matters less than expected. The DWSIM bundled `Petroleum Distillation.dwxml` sample already has 30 PSE_3165_* pseudocomponents pre-characterized. Use it as the substrate. Do not rebuild characterization programmatically unless absolutely required.

## 6. Compound database keys (verified)

DWSIM ships with 1,487 compounds. Common refinery names use these EXACT case-sensitive keys:

```
'Ethane'        — single key
'Propane'       — single key
'Isobutane'     — preferred (also 'IsoButane' duplicate exists)
'n-Butane'      — preferred (also 'N-butane' duplicate exists)
'Water'         — for steam stripping
'Methane'       — single key
```

Important: Multiple keys exist for some compounds because DWSIM bundles multiple databases (ChemSep, ChEDL, etc.). Pick one casing and stick with it.

## 7. What we KNOW works (data extraction)

For digital twin work, these reads are PROVEN reliable:

```python
# Material stream properties
ms = sim.SimulationObjects[stream_id]
ms.GetPropertyValue("PROP_MS_0")   # Temperature (K)
ms.GetPropertyValue("PROP_MS_1")   # Pressure (Pa)
ms.GetPropertyValue("PROP_MS_2")   # Mass flow (kg/s)
ms.GetPropertyValue("PROP_MS_3")   # Mole flow (mol/s)
ms.GetPropertyValue("PROP_MS_4")   # Volume flow (m³/s)
ms.GetPropertyValue("PROP_MS_27")  # Vapor fraction
# Plus PROP_MS_xx for density, enthalpy, entropy, etc.

# Composition (per compound)
for comp_name in sim.SelectedCompounds.Keys:
    mole_frac = ms.Phases[0].Compounds[comp_name].MoleFraction
    mass_frac = ms.Phases[0].Compounds[comp_name].MassFraction

# Column stage data (per stage)
col = sim.SimulationObjects[col_id]
for i in range(col.NumberOfStages):
    stage = col.Stages[i]
    T = stage.T          # Kelvin
    P = stage.P          # Pa
    V = stage.V          # vapor flow
    L = stage.L          # liquid flow

# Energy stream
es = sim.SimulationObjects[energy_id]
duty = es.EnergyFlow    # Watts
```

Tag count from a 12-stage Petroleum Distillation sample:

- 5 material streams × ~50 tags = 250
- 1 column × 12 stages × 30 compositions = 360
- 2 energy streams × 1 tag = 2
- Total ~620 tags per solve cycle

This is sufficient for a credible digital twin demo.

## 8. The methodology that survived (carry forward)

These principles emerged from 10 days of pain. Apply them to digital twin work too.

### Atomic ladder
One change per increment. Solve and verify between each change. If you must add 20 compounds, add them 5 → 6 → 7 → 8 → ... → 20, not 5 → 20.

### Verify-after-write
After mutating any property, re-read it and assert it matches expected. DWSIM's serialization layer can silently mangle values (Bug Class 3).

### Verify chemistry, not just convergence
`sim.Solved == True` is necessary but not sufficient. Read distillate composition, bottoms composition, and key duties. False convergence is real (Bug Class 6).

### Save before solve
Solve attempts can crash the .NET runtime. Save the flowsheet artifact BEFORE every solve attempt. This way, on crash, you can resume.

### Refuse-if-exists
Build scripts must `sys.exit(1)` if their target .dwxmz already exists. No silent overwrite. Forces explicit cleanup and prevents accidental data loss.

### Probe before fix
For ANY error class beyond simple convergence failure, write a probe script first that introspects the API surface (`obj.GetType().GetMethods()`) and report findings. Do not guess at fixes. 3-attempt cap before reporting back.

### Clean build, not load-and-modify
For complex flowsheets with structural changes, building from scratch is more reliable than loading-and-mutating. The mutation surface is brittle (Bug Class 7, 8). Loaded files carry hidden state.

## 9. What worked vs what failed strategically

### What worked

- MVP atomic ladder (5→12 compounds, single column): Locked working artifact in `MVP_Canonical_12Compound_Final.dwxmz`. Solves in 11.84s.
- Bundled DWSIM sample (`Petroleum Distillation.dwxml`): 12 stages, 30 pseudocomponents, 5 streams. Solves in 3.8s. This is the digital twin substrate.
- Probe-first methodology: Saved hours when DWSIM API didn't match assumptions.
- The 2-arg MessageListener pattern: After multiple 1-arg failures.

### What failed

- Watkins/Bagajewicz canonical CDU rebuild: 34 trays + 3 side strippers + 3 pumparounds. Hit 8 bug classes. 3 days of debugging without converging. Abandon for digital twin scope.
- UI-based Petroleum Characterization workflow: Worked once for 29 compounds but isn't reproducible (no script trail). Reset for 10+ minutes per attempt.
- Programmatic Petroleum Characterization: API exists but curve input fields are private. Blocked.

## 10. The strategic recommendation for the new chat

```
DO NOT attempt to build a custom CDU simulation for digital twin work.

USE the bundled Petroleum Distillation sample as Feature 4 substrate.
  Path: /Applications/DWSIM.app/Contents/MonoBundle/samples/Petroleum Distillation.dwxml
  Topology: 12-stage column, 30 pseudocomponents, 5 product streams
  Property package: Peng-Robinson
  Solver: Wang-Henke
  Solve time: ~4 seconds
  Status: PROVEN to converge cleanly via Automation3

WRAP it in a scheduled solve loop (every 30s or per setpoint change).
EXTRACT ~620 tags per cycle into a structured snapshot.
EMIT to Azure (Event Hubs) and/or local OPC-UA server.

DO NOT touch the chemistry layer. Spend the engineering on the twin layers.
```

## 11. File and artifact locations

```
DWSIM installation:
  /Applications/DWSIM.app/Contents/MonoBundle/    — DLLs and samples

Sample (read-only, do not modify):
  /Applications/DWSIM.app/Contents/MonoBundle/samples/Petroleum Distillation.dwxml

Working files:
  ~/Documents/AISolutions/RefineryTwin/DWSIM/    — saved .dwxmz files
  ~/Documents/AISolutions/RefineryTwin/automation/    — Python scripts and venv

Backups (auto-saved by DWSIM every 3 min while open):
  ~/Documents/DWSIM Application Data/Backup/
```

## 12. What the new architect Claude should know about this user

```
Sowthri — chemical engineer, Dammam Saudi Arabia.
Has been building this for 10 days.
Hit a wall with custom CDU. Pivoting to digital twin platform demo.
Operating model: architect (Claude) writes briefings,
                 implementer (Claude Code) executes,
                 operator (Sowthri) approves and runs.

Token-conscious, no fluff.
Direct pushback welcome.
Standalone identity rule active (no references to prior employer/projects).

Goal NOW: 5-feature digital twin demo on Azure-native stack
          using DWSIM Petroleum Distillation sample as Feature 4 substrate.
```

## 13. The "do not redo" list

These have been done. Do not re-litigate or rebuild.

```
✗ Don't probe DWSIM API basics — patterns above are proven
✗ Don't try to fix Petroleum Characterization curve-input issue
✗ Don't try to build custom CDU from scratch
✗ Don't second-guess the toolchain (it works)
✗ Don't try Petroleum Characterization in Python (private API)
✗ Don't try Bagajewicz Steps 1-6 convergence sequence (out of scope)
✗ Don't research alternative solvers (Wang-Henke works for our substrate)
```

## 14. The simulation loop pattern (untested but architecturally sound)

For Feature 4 (Simulation), expected pattern:

```python
import time
from datetime import datetime

# Load once, solve many times
sim_auto = Automation3()
sim = sim_auto.LoadFlowsheet(SAMPLE_PATH)
sim.AddListener(...)

# Optional: setpoint inputs from Azure / REST / OPC-UA
def get_current_setpoints():
    # Read from Event Hubs control queue, REST POST endpoint, etc.
    return {"reflux_ratio": 2.5, "feed_temp": 350}

# Main loop
while True:
    # Apply setpoints
    setpoints = get_current_setpoints()
    apply_setpoints(sim, setpoints)

    # Solve
    t_start = time.time()
    sim_auto.CalculateFlowsheet4(sim)
    t_solve = time.time() - t_start

    # Extract snapshot
    snapshot = {
        "timestamp": datetime.utcnow().isoformat(),
        "solved": sim.Solved,
        "solve_time_s": t_solve,
        "streams": extract_all_streams(sim),
        "column": extract_column_state(sim),
        "energy": extract_energy_streams(sim),
    }

    # Emit to Azure / local store / OPC-UA
    emit_snapshot(snapshot)

    # Sleep to next cycle
    time.sleep(SOLVE_INTERVAL)
```

Solve time is ~4s for the sample, so cycle interval can be 10-30s comfortably.

---

*End of knowledge base. Hand this to the next architect chat as opening context. Anything not in this document is fair game to revisit; everything in this document was learned the hard way.*
