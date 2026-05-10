# Phase 0a Briefing — Substrate Inventory Probe

**Project:** Refinery Digital Twin · Feature 4 substrate inventory
**Issued by:** Architect chat
**Implementer:** Claude Code (next session)
**Operator:** Sowthri (approves and runs)
**Status:** Day 11 Priority #1
**Estimated effort:** 1.5 hr implementer + 30 min operator review

---

## Goal

Inventory every readable property and writable spec in the locked substrate flowsheet. The output is the canonical tag and setpoint dictionary that all subsequent Features (Data Fabric, Twin, Agentic AI, Experience) depend on.

This is a one-shot probe. Runs once, produces artifacts, never runs again as part of normal operation.

## Substrate

| | |
|---|---|
| File | `Petroleum Distillation with Reboiler Heating Fluid.dwxmz` |
| Path (verified) | `/Applications/DWSIM.app/Contents/MonoBundle/samples/` |
| State | **LOCKED** — do not modify under any circumstance |
| Format | Compressed `.dwxmz` (Automation3 handles transparently) |
| Convergence | **Confirmed** — operator ran solve, full results report attached as ground truth |
| Property packages | Two: Peng-Robinson (petroleum side) + CoolProp Incompressible (thermal oil loop) |

### Substrate ground truth

The operator has provided a successful solve report. Use it to validate the inventory output, not to skip the inventory.

**Two coupled subsystems:**

*Petroleum side (Peng-Robinson):*
- Material streams: `Oil` (3-phase feed: Overall + Vapor + Liquid), `Light Product`, `Light Intermediate product`, `Intermediate Product`, `"Heavy" Product`
- Distillation Column: 12 stages, total condenser, condenser duty 29.76 MW, reboiler duty −27.28 MW
- 30 pseudocomponents: `PSE_3165_2` through `PSE_3165_31` (note: starts at index 2)

*Thermal oil loop (CoolProp Incompressible Fluids):*
- Material streams: `Therminol VP1`, `MSTR-010`, `MSTR-013`, `MSTR-014`, `MSTR-018`
- Heaters: `Thermal Oil Heating` (27.28 MW), `Reboiler (Proxy)` (proxy that closes the energy hand-off to the column)
- Pump: `Thermal Oil Pump` (Δp 100 kPa, 75 % efficiency, 27.86 kW)
- Tank: `Therminol VP1 Storage Tank`
- Recycle Block: `REC-012`
- Specification Blocks: `SPEC-02`, `SPEC-020`

*Energy streams:* `Condenser Duty`, `Reboiler Duty`, `Reboiler Duty (2)`, `Heating Duty`, `ESTR-017` (pump power)

**Composition note (critical for inventory):** Therminol-loop streams show uniform 0.03333 mole fraction across all 30 pseudocomponents. CoolProp Incompressible ignores composition by design. These tags are valid but static — flag them.

## Required reading before any code

1. `DWSIM_KNOWLEDGE_BASE.md` — toolchain, 8 bug classes, working patterns
2. `STREAMING_PLAN.md` Part A — Probe-and-Solve methodology and probe template
3. This briefing

If anything in this briefing contradicts the KB, the KB wins. Flag the contradiction and stop.

## Toolchain (do not deviate)

- macOS Sequoia, Apple Silicon
- Mono x86_64 via Rosetta 2
- Python 3.9.6+ in x86_64 venv (proven working version)
- pythonnet 3.0.5 (NOT 3.0.4)
- macOS Full Disk Access granted to Terminal

**Venv location (fresh, project-local):**
`~/Documents/AISolutionPortfolio/2.AssetsAI/1.RefineryDigitalTwin/2.automation/.venv-x86/`

The operator (Sowthri) creates and verifies this venv before invoking you. Do not attempt to create it yourself; if `arch -x86_64 .../.venv-x86/bin/python -c "import clr"` fails, stop and report — that's an operator setup issue, not an implementer fix.

**Run pattern (from `2.automation/phase0a/`):**
```
arch -x86_64 ../.venv-x86/bin/python probe.py
```

## Inputs

- Path to substrate file (CLI arg, default: standard location above; verify exists before opening)
- Output directory (CLI arg, default: `~/Documents/AISolutionPortfolio/2.AssetsAI/1.RefineryDigitalTwin/3.probes/phase0a/`; create if missing)

## Behavior

### 1. Bootstrap
- Add references to `DWSIM.Automation.dll`, `DWSIM.Interfaces.dll`, `DWSIM.Thermodynamics.dll` from `/Applications/DWSIM.app/Contents/MonoBundle/`
- Construct `Automation3()`
- Register the 2-arg `MessageListener` via `Action[object, object]`. Listener writes to stdout **and** appends to `phase0a_probe.log`. Never use the 1-arg form (KB §3).

### 2. Pre-flight (refuse-if-exists)
- Verify substrate file exists at given path; fail loudly if not
- Verify all six output paths do **NOT** exist (and the pre-solve `.dwxmz` baseline path); fail with `sys.exit(1)` if any do
- Print the run plan (paths, args) to stdout before starting

### 3. Load
- `sim_auto.LoadFlowsheet(path)` — handles `.dwxmz` transparently
- Capture: compound count, list of compound IDs, **all** property packages (substrate has two), simulation object count
- For each `SimulationObject`, determine and record its associated property package — needed for the `subsystem` tag in step 10
- Detect if flowsheet arrives pre-solved (the substrate does); log either way

### 4. Save before solve
- Copy substrate to `<output_dir>/phase0a_substrate_pre_solve.dwxmz` before any solve attempt (KB §8 — solve attempts can crash the .NET runtime)

### 5. Solve
- Record `t0 = time.time()`
- `errors = sim_auto.CalculateFlowsheet4(sim)` — note: returns list of exceptions, not status
- Record `solve_duration_s = time.time() - t0`
- Assert `sim.Solved == True`; on failure, dump `sim.ErrorMessage`, length of `errors`, first 3 error reprs to log and exit non-zero

### 6. Chemistry verification (gating guards, not warnings)

These are hard gates. If any fail, write `findings.md` noting the failure and exit non-zero.

- **Bug Class 4 guard.** For every material stream, assert `len(stream.Phases[0].Compounds) == sim.SelectedCompounds.Count`. Any mismatch is a zombie composition.
- **Bug Class 6 guard (substrate-specific).** Identify the `Light Product` stream. Assert it has ≥10 compounds at mole fraction > 0.01. The ground-truth report shows 27+ such compounds, so this is loose by design — a tighter check would mask drift. Log the top 10 compositions for sanity.
- **Bug Class 8 guard.** For each column, assert `column.NumberOfStages == column.Stages.Count`. Any mismatch is structural corruption.
- **Static-composition note (not a guard).** Streams in the thermal oil loop will show uniform 0.0333 across compounds. This is by design (CoolProp Incompressible). Do *not* fail on it; flag it in step 7.

### 7. Inventory walk

For **every** `SimulationObject` in `sim.SimulationObjects`:
- `GraphicObject.Tag` (UI display name)
- Internal name (GUID-style handle)
- `ObjectType` (string from enum)
- `Calculated` flag
- `property_package` (PR or CoolProp Incompressible)
- `subsystem`: `petroleum` if PR, `thermal_oil` if CoolProp — derived field, used downstream

Then per object type:

**Material streams**
- All `PROP_MS_*` properties. Probe by starting at `PROP_MS_0` and incrementing until `GetPropertyValue` raises. Record the index range that worked.
- For each successful property: numeric value + declared unit
- **Phase handling.** Detect phase configuration:
  - Single-phase (most streams): emit one set of thermo + composition tags with flat tag IDs
  - Multi-phase (Oil): emit three sets — `OVERALL`, `VAPOR`, `LIQUID` — each with its own thermo + composition tags
- Per-phase per-compound mole fraction and mass fraction
- Phase state code, vapor fraction
- **Static-composition flag.** If `subsystem == thermal_oil`, set `static_composition: true` and `composition_meaningful: false` on every composition tag for that stream. Petroleum streams keep `composition_meaningful: true`.

**Columns**
- `NumberOfStages`, `Stages.Count` (logged separately even after parity guard)
- Per-stage vector: `T` (K), `P` (Pa), `V` (mol/s), `L` (mol/s), liquid composition (dict of compound → mole frac)
- Condenser duty, reboiler duty (with sign)
- `IC` (internal iteration count), `EC` (external iteration count)
- Reflux ratio
- Spec properties — probe via `column.GetType().GetProperties()`, capture writable ones with current value

**Energy streams**
- `EnergyFlow` (W) with sign

**Heaters and pumps**
- Probe property surface via `obj.GetType().GetProperties()`
- Capture all readable values: inlet T/P, outlet T/P, duty, efficiency, pressure drop, calculation mode
- Mark all writable as candidate setpoints

**Tank** (`Therminol VP1 Storage Tank`)
- Probe `obj.GetType().GetProperties()` — minimal report surface in PDF means we discover via introspection
- Capture every readable property; flag any writable as candidate setpoint
- Likely surface: volume, level, holdup, residence time — record what's actually there

**RecycleBlock** (`REC-012`)
- Probe `obj.GetType().GetProperties()`
- Specifically capture (if present): convergence tolerances, last iteration error, max iterations, current iteration count
- These are valuable because they tell the streamer how the loop is doing

**SpecificationBlock** (`SPEC-02`, `SPEC-020`)
- Probe `obj.GetType().GetProperties()`
- Capture: target object reference, target property name, source object/property (if it's an equality between two), enforced value or rule expression, active flag
- These are **constraints, not setpoints** — they go in `constraint_dictionary.json` (see step 9), not the setpoint dictionary
- Note the goal: SPEC-020 appears to enforce energy balance closure between subsystems; SPEC-02 appears to enforce a temperature differential. Confirm or correct in findings.

If you encounter an `ObjectType` not listed above, **probe first** (KB §10) and add a clearly named extractor. Do not silently skip.

### 8. Setpoint identification (vs. constraints)

A property is a **setpoint candidate** if all of:
- The owning object is *not* a `SpecificationBlock` (those go to constraints, not setpoints)
- AND any of:
  - The owning object has `Calculated == False`
  - The property name matches a known spec pattern: `Spec_*`, `RefluxRatio`, `RR`, `Temperature`, `Pressure` on input streams, `OutletTemperature` on heaters, `PressureDrop` on heaters/pumps, `Efficiency`
  - `PropertyInfo.CanWrite == True` and the property is on a unit op the operator would tune

For each setpoint:
- Owner object Tag
- Property key
- Current value, unit
- Suggested perturbation bounds: ±20 % of current value as default. For temperatures, ±20 K. For mole fractions, [0.01, 0.99]. For efficiency, [0.5, 1.0].

`SpecificationBlock` instances do NOT go in `setpoint_dictionary.json`. They go in `constraint_dictionary.json`:
- `constraint_id`: spec block tag (e.g. `SPEC-020`)
- `target_object`, `target_property`: what it acts on
- `source_object`, `source_property`: if it's an equality between two values
- `rule`: text description (e.g. "Heating Duty = -Reboiler Duty (2)")
- `current_target_value`: current resolved value
- `active`: bool

### 9. Outputs

All six files written to output directory. **All six refuse-if-exists**.

| File | Purpose |
|---|---|
| `phase0a_probe.log` | DWSIM listener output + full script trace, append mode |
| `phase0a_inventory.json` | Machine-readable everything: per-object, per-property, with value, type, unit, calculated flag, property package, subsystem |
| `phase0a_tag_dictionary.json` | Flat list of **read** tags with stable hierarchical IDs (schema below) |
| `phase0a_setpoint_dictionary.json` | **Writable** specs with values, units, owner, suggested bounds — excludes SpecificationBlock entries |
| `phase0a_constraint_dictionary.json` | **SpecificationBlock** entries: target/source refs, rule, current value, active flag |
| `phase0a_findings.md` | Human-readable findings, template below |

Plus `phase0a_substrate_pre_solve.dwxmz` from step 4 — keep it as the verified pre-solve baseline.

### 10. Tag ID convention

Stable, hierarchical, parseable. The Twin Builder ontology in Feature 2 will map these to asset paths.

```
<ObjType>-<Tag>[.<PHASE>].<PropertyKey>[.<modifier>]

Examples (substrate-real):
MS-OIL.OVERALL.PROP_MS_0                       Oil feed, overall phase, temperature
MS-OIL.VAPOR.PROP_MS_2                         Oil feed, vapor phase, mass flow
MS-OIL.LIQUID.MoleFraction.PSE_3165_27         Oil feed, liquid phase, mole frac PSE_3165_27
MS-LIGHT_PRODUCT.PROP_MS_0                     Light Product (single-phase), temperature
MS-MSTR-018.PROP_MS_0                          Thermal oil stream MSTR-018, temperature
MS-THERMINOL_VP1.MoleFraction.PSE_3165_15      Therminol VP1 (static composition; flagged)
COL-DISTILLATION_COLUMN.STAGE-3.T              Column, stage 3, temperature
COL-DISTILLATION_COLUMN.RefluxRatio            Column, reflux ratio
COL-DISTILLATION_COLUMN.CondenserDuty          Column, condenser duty
ES-CONDENSER_DUTY.EnergyFlow                   Energy stream Condenser Duty
ES-RBL_DUTY_2.EnergyFlow                       Energy stream Reboiler Duty (2)
HC-THERMAL_OIL_HEATING.OutletTemperature       Heater Thermal Oil Heating, outlet T
HC-REBOILER_PROXY.PressureDrop                 Heater Reboiler (Proxy), pressure drop
PMP-THERMAL_OIL_PUMP.Power                     Pump Thermal Oil Pump, power
TANK-THERMINOL_VP1_STORAGE.<discovered>        Tank — fields by introspection
RECYCLE-REC_012.Iterations                     Recycle block, iteration count
```

Tag-name normalization rule for ObjType prefix:
- `MS` material stream, `COL` column, `ES` energy stream, `HC` heater/cooler, `PMP` pump, `TANK` tank, `RECYCLE` recycle block, `SPEC` not used in tag dict (constraints, see step 8)

Each tag entry in `tag_dictionary.json`:
```json
{
  "tag_id": "MS-OIL.OVERALL.PROP_MS_0",
  "owner_tag": "Oil",
  "owner_type": "MaterialStream",
  "phase": "OVERALL",
  "property_key": "PROP_MS_0",
  "description": "Temperature",
  "unit_si": "K",
  "current_value": 350.0,
  "category": "stream_thermo",
  "subsystem": "petroleum",
  "property_package": "Peng-Robinson (PR)",
  "static_composition": false,
  "composition_meaningful": true
}
```

For non-composition tags, set `static_composition: false` and omit `composition_meaningful` (or leave as `null`). The flag pair is meaningful only on composition tags.

Categories: `stream_thermo`, `stream_composition`, `column_stage`, `column_global`, `energy`, `heater`, `pump`, `tank`, `recycle`, `other` — extend as needed.

### 11. Findings.md template

Follow the Part A structure exactly. Five sections, no fewer.

```markdown
# Phase 0a Findings — Substrate Inventory

## 1. What was probed
- File: <path>
- DWSIM version: <from automation>
- Compounds: <count> — list (PSE_3165_2 through PSE_3165_31 expected)
- SimulationObjects: <count> by ObjectType breakdown
- Property packages: petroleum side <list>; thermal oil side <list>
- Solver: <name>, tolerances: <values if discoverable>
- Solve time: <duration>s
- Pre-solved on load: <yes/no>

## 2. What was found

### Petroleum subsystem
**Material streams (<N>):** Oil, Light Product, Light Intermediate product, Intermediate Product, "Heavy" Product
**Column:** Distillation Column — <stages>, <duties>, <RR>
**Confirms ground truth:** <yes/no/discrepancies>

### Thermal oil subsystem
**Material streams (<N>):** Therminol VP1, MSTR-010, MSTR-013, MSTR-014, MSTR-018
**Heaters:** Thermal Oil Heating, Reboiler (Proxy) — <duties, ΔP, efficiency>
**Pump:** Thermal Oil Pump — <power, ΔP, efficiency>
**Tank:** Therminol VP1 Storage Tank — <fields discovered>
**Recycle Block:** REC-012 — <iterations, tolerance, last error>
**Confirms ground truth:** <yes/no/discrepancies>

### Energy streams (<N>)
List: tag, EnergyFlow, sign convention, subsystem

### Constraints (SpecificationBlocks)
For SPEC-02, SPEC-020 — what each enforces, current values, active flag

### Total tag count: <N>
Breakdown by category and subsystem:
- petroleum / stream_thermo: <N>
- petroleum / stream_composition: <N>
- petroleum / column_stage: <N>
- petroleum / column_global: <N>
- thermal_oil / stream_thermo: <N>
- thermal_oil / stream_composition (static): <N>
- thermal_oil / heater: <N>
- thermal_oil / pump: <N>
- thermal_oil / tank: <N>
- thermal_oil / recycle: <N>
- energy: <N>

### Setpoint count: <N>
Top candidates by leverage (operator's view of what's worth perturbing first)

### Constraint count: <N>
SpecificationBlock entries with rule descriptions

## 3. What is blocked
- Any object type that didn't yield to introspection
- Any property that raised on read with non-trivial reason
- Any spec block whose rule couldn't be cleanly extracted
- (If empty, say so explicitly)

## 4. Proposed paths forward
- Streamer Stage 1 should consume `phase0a_inventory.json` and emit the snapshot schema in STREAMING_PLAN.md Part C — extended to carry the `subsystem` field
- Note any schema deltas vs Part C
- Note cycle interval recommendation given measured solve time

## 5. Architect decision point
- Anything that requires a call from this chat before Stage 1 streamer is built
- (If none, say so explicitly)
```

## Acceptance criteria

- [ ] File path verified, file loaded
- [ ] `sim.Solved == True` after `CalculateFlowsheet4`
- [ ] Solve duration captured (expected 3–6 s; flag if >10 s)
- [ ] Pre-solve baseline `.dwxmz` saved
- [ ] Bug Class 4 guard passes for every material stream
- [ ] Bug Class 6 guard passes (Light Product ≥10 compounds >0.01 mol frac)
- [ ] Bug Class 8 guard passes for every column
- [ ] Tag count ≥ 1200 (substrate ground truth implies 1500–2000); flag if outside [800, 2500]
- [ ] Setpoint count ≥ 5
- [ ] Constraint count = 2 (SPEC-02, SPEC-020); flag if different
- [ ] Property packages detected: PR and CoolProp Incompressible (both must be present)
- [ ] Subsystem field populated on every tag entry (`petroleum` or `thermal_oil`)
- [ ] All six output artifacts written, plus pre-solve baseline
- [ ] Re-running script exits non-zero (`refuse-if-exists` works)
- [ ] `findings.md` has all five sections, none empty (use "(none)" if applicable)
- [ ] Operator reviews `findings.md` and either approves or files an architect decision
- [ ] Inventory output cross-checks against the substrate ground-truth report (key values: condenser duty 29.76 MW, reboiler duty −27.28 MW, Therminol mass flow 200 kg/s, Oil vapor fraction 0.172, 12 column stages)

## Anti-goals (KB §13)

- ✗ Do NOT modify the substrate file
- ✗ Do NOT add or remove compounds
- ✗ Do NOT attempt Petroleum Characterization writes
- ✗ Do NOT propose alternative substrates
- ✗ Do NOT touch chemistry layer
- ✗ Do NOT stream the inventory anywhere (Stage 1 is separate briefing)
- ✗ Do NOT solve with perturbed inputs (that's post-Stage 1)
- ✗ Do NOT emit to Azure (Stage 5, way later)

## Methodology rules (universal)

- `save-before-solve` — done in step 4
- `verify-after-write` — when reading, capture both value and declared type/unit; type mismatches log as warnings
- `refuse-if-exists` — `sys.exit(1)` on any pre-existing output, no overwrite, no `--force` flag
- `2-arg MessageListener` — `Action[object, object]`, never 1-arg
- `probe before assuming` — any object type beyond stream/column/energy: introspect first
- `3-attempt cap` — if any guard fails 3 times across 3 separate runs, **STOP** and report `findings.md` as-is with the failure mode in section 5

## Out of scope

- Streaming, snapshots, sinks (Stage 1+, separate briefings)
- Setpoint perturbation
- Cloud emission
- OPC-UA
- Any modification of the flowsheet
- Tag → ontology mapping (Feature 2)
- Any frontend or dashboard work

## Definition of done

The phase is complete when:
1. All six output artifacts exist in the output directory
2. Pre-solve baseline `.dwxmz` exists
3. All acceptance criteria boxes are checked
4. Inventory ground-truth cross-check passes (matches the operator's converged solve report on key values)
5. Operator has read `phase0a_findings.md`
6. Either:
   - Findings clean → operator approves → architect issues Stage 1 streamer briefing
   - Findings flag a decision point → operator notifies architect → resolved in chat before Stage 1

## Hand-off note for Claude Code

This is a probe, not a build. The output is *information*, not a service. Bias toward more introspection, less cleverness. If you encounter anything in the substrate the KB and STREAMING_PLAN didn't anticipate, document it in `findings.md` section 3 ("What is blocked") and section 5 ("Architect decision point") rather than inventing a workaround. The architect chat will resolve.

End of briefing.
