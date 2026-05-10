# Phase 0a Findings — Substrate Inventory

## 1. What was probed

- File: `/Applications/DWSIM.app/Contents/MonoBundle/samples/Petroleum Distillation with Reboiler Heating Fluid.dwxmz`
- Probe version: 0a-1.2
- Timestamp: 2026-05-09T20:09:56.914902+00:00
- Compounds: 30 — first 3: ['PSE_3165_2', 'PSE_3165_3', 'PSE_3165_4'], last 3: ['PSE_3165_29', 'PSE_3165_30', 'PSE_3165_31']
- SimulationObjects: 23; breakdown:
    - column: 1
    - energy_stream: 5
    - heater: 2
    - material_stream: 10
    - pump: 1
    - recycle: 1
    - spec_block: 2
    - tank: 1
- Property packages (from collection):
    - id='PP-19e6f4c4-fd9e-436a-94a8-bdd812e204d9', name='Peng-Robinson (PR)', type=IPropertyPackage
    - id='PP-b0987e8c-cb43-4628-9cb5-b4f7b1b4109e', name='CoolProp (Incompressible Fluids)', type=IPropertyPackage
- Property packages (from per-object reads, post-walk):
    - CoolProp (Incompressible Fluids)
    - Peng-Robinson (PR)
- Listener registered: False (KB §3 drift in DWSIM 9.0.5 macOS)
- Solve duration: 3.040s
- Pre-solved on load: False

## 2. What was found

### Petroleum subsystem
**Material streams (5):** "Heavy" Product, Intermediate Product, Light Intermediate product, Light Product, Oil
**Column:** 'Distillation Column' — NumberOfStages=12, Stages.Count=12, RR=2.4987072531873755, CondenserDuty=29755.277819677172 kW, ReboilerDuty=-27281.184948998965 kW
**Confirms ground truth:** see cross-check table below

### Thermal oil subsystem
**Material streams (5):** MSTR-018, MSTR-014, MSTR-013, MSTR-010, Therminol VP1
**Heaters:** Thermal Oil Heating, Reboiler (Proxy)
**Pumps:** Thermal Oil Pump
**Tanks:** Therminol VP1 Storage Tank
**Recycle Blocks:** REC-012

### Energy streams
- 'Heating Duty': EnergyFlow = 27275.7263999042 kW, subsystem = thermal_oil
- 'ESTR-017': EnergyFlow = 27.859033700250446 kW, subsystem = thermal_oil
- 'Condenser Duty': EnergyFlow = 29755.277819677172 kW, subsystem = petroleum
- 'Reboiler Duty': EnergyFlow = -27275.7263999042 kW, subsystem = petroleum *(architect override — see §3)*
- 'Reboiler Duty (2)': EnergyFlow = 27281.184948998965 kW, subsystem = petroleum

### Constraints (SpecificationBlocks)
- **SPEC-020** — type Spec, target='Heating Duty'/'Heating Duty', source='Reboiler Duty (2)'/'Reboiler Duty (2)', active=True
- **SPEC-02** — type Spec, target='Reboiler Duty'/'Reboiler Duty', source='Reboiler Duty (2)'/'Reboiler Duty (2)', active=True

### Total tag count: 1550 (post architect override: petroleum 656, thermal_oil 894)
Breakdown by subsystem / category:
- petroleum / column_global: 5
- petroleum / column_stage: 24
- petroleum / energy: 3
- petroleum / stream_composition: 360
- petroleum / stream_thermo: 264
- thermal_oil / energy: 2
- thermal_oil / heater: 136
- thermal_oil / pump: 79
- thermal_oil / recycle: 61
- thermal_oil / stream_composition: 300
- thermal_oil / stream_thermo: 255
- thermal_oil / tank: 61 *(Storage Tank — architect override, see §3)*
- Static-composition tags (thermal-oil compositions): 300

### Setpoint count: 39 (25 perturbable, 14 non-perturbable)

Top 10 perturbable (operating setpoints — Stage 1 streamer feeds these):
- `Thermal Oil Heating` / `OutletTemperature` = 490.633 K (bounds: ±20 K)
- `Thermal Oil Heating` / `HeatDuty` = 27275.7 kW (bounds: ±20%)
- `Thermal Oil Heating` / `Efficiency` = 100.0% (bounds: [50, 100])
- `Thermal Oil Heating` / `PressureDrop` = 50000.0 Pa (bounds: ±20%)
- `Thermal Oil Pump` / `OutletTemperature` = 422.4 K (bounds: ±20 K)
- `Thermal Oil Pump` / `Efficiency` = 75.0% (bounds: [50, 100])
- `Thermal Oil Pump` / `DeltaP` = 100000.0 Pa (bounds: ±20%)
- `Reboiler (Proxy)` / `HeatDuty` = -27275.7 kW (bounds: ±20%)
- `Distillation Column` / `RefluxRatio` = 2.499 (bounds: ±20%)
- `Distillation Column` / `CondenserDuty` = 29755.3 kW (bounds: ±20%)

Non-perturbable (14 — held from harness per architect rule):
- 9 × `DebugMode = False` and `CalcMode = N` (bool/enum across heaters/pumps/recycle/tank)
- `Thermal Oil Pump / FixOnDeltaP = True`
- `REC-012 / LegacyMode = True`
- `Distillation Column / UseTemperatureEstimates = False`
- `Therminol VP1 Storage Tank / DeltaP = None` (uncomputed)
- `Distillation Column / ColumnPressureDrop = None` (uncomputed)

### Constraint count: 2
- `SPEC-020`: Spec, target='Heating Duty'/'Heating Duty'
- `SPEC-02`: Spec, target='Reboiler Duty'/'Reboiler Duty'

### Chemistry guards
- Bug 4 (zombie composition): PASS — 0 failures, expected_compound_count=30
- Bug 6 (false convergence on Light Product): PASS — 26 compounds above 0.01 mole frac (need ≥10)
  Top 10 compositions in Light Product:
    - PSE_3165_2: 0.0506
    - PSE_3165_3: 0.0501
    - PSE_3165_4: 0.0492
    - PSE_3165_6: 0.0489
    - PSE_3165_5: 0.0486
    - PSE_3165_7: 0.0474
    - PSE_3165_9: 0.0473
    - PSE_3165_8: 0.0468
    - PSE_3165_10: 0.0454
    - PSE_3165_12: 0.0452
- Bug 8 (Stages.Count == NumberOfStages): PASS — 0 failures

### Ground-truth cross-check
- PASS condenser_duty_kW: expected ~29760.0, got 29755.277819677172, tolerance=0.05
- PASS reboiler_duty_kW: expected ~-27280.0, got -27281.184948998965, tolerance=0.05
- PASS therminol_mass_flow_kg_s: expected ~200.0, got 200.0, tolerance=0.05
- PASS oil_vapor_fraction: expected ~0.172, got 0.17157324296600474, tolerance=0.05
- PASS column_stages: expected ~12, got 12, tolerance=0.0
- PASS compound_count: expected ~30, got 30, tolerance=0.0

## 3. What is blocked

(none) — but two **architect overrides applied** post-attempt-3 to resolve subsystem-classification ambiguities:

- **Storage Tank PP-vs-topology disagreement.** DWSIM reports `Therminol VP1 Storage Tank.PropertyPackage = Peng-Robinson (PR)` (a stale assignment from initial flowsheet construction). Topologically and operationally the tank is part of the thermal oil loop. Architect rule: **when DWSIM property-package metadata disagrees with topology, topology wins.** Override applied: `Therminol VP1 Storage Tank` and its 61 tags → `thermal_oil`.

- **`Reboiler Duty` energy stream sits at the subsystem hand-off.** Topology trace landed on the Reboiler (Proxy) heater (thermal_oil) because both endpoints connect there. Operator/agent convention identifies the stream as the column's reboiler duty (petroleum side). Architect rule: **energy streams that sit at the subsystem hand-off are classified by name/convention, not pure trace.** Override applied: `Reboiler Duty` → `petroleum`. The constraint dictionary entries (SPEC-02 enforces `Reboiler Duty = -Reboiler Duty (2)`, SPEC-020 enforces `Heating Duty = Reboiler Duty (2)`) confirm the hand-off geometry.

These overrides are recorded in `phase0a_inventory.json.meta.architect_overrides_applied` for downstream reproducibility.

## 4. Proposed paths forward

- Streamer Stage 1 should consume `phase0a_inventory.json` and emit the snapshot schema in STREAMING_PLAN.md Part C, extended with the `subsystem` field on every stream/op. The schema delta is: `subsystem: 'petroleum' | 'thermal_oil'` at the object level; per-tag entries inherit it.
- Cycle interval recommendation: solve took 3.04s; the briefing's 30 s default holds.
- For multi-phase Oil, this probe emits OVERALL/VAPOR/LIQUID per the briefing; downstream snapshot schema needs a `phase` discriminator on stream tags.
- Thermal-oil streams have `static_composition=true` / `composition_meaningful=false`. Streamer should de-prioritise these tags but emit them for completeness; dashboards can hide them.
- **Subsystem classification rules going forward** (architect-confirmed):
  1. *Topology wins over PP metadata* when they disagree (Storage Tank case).
  2. *Energy streams at subsystem hand-off classified by name/convention*, not pure trace (Reboiler Duty case).
- **Setpoint perturbation harness**: only entries with `perturbable: true` are tunable. Non-numeric writables (enums, bools — e.g. `DebugMode`, `CalcMode`) are marked `perturbable: false` per architect rule (they change simulation structure, not operating point). Streamer Stage 1 ignores them; agents may read them as metadata.

## 5. Architect decision point

All architect decisions resolved at Phase 0a closure:

- ✓ **DWSIM 2-arg MessageListener (KB §3) drift confirmed.** IFlowsheet in 9.0.5 macOS exposes no `AddListener` / `OnMessage` / `MessageListener`. Python-side stdout/stderr capture is the proven pattern going forward. KB §3 update queued, non-blocking.
- ✓ **Non-perturbable setpoints held from perturbation harness.** 14 entries marked `perturbable: false` in `setpoint_dictionary.json` (12 calculation-mode toggles — bools/enums, plus 2 with `current_value: None`). Streamer Stage 1 ignores; agents may read as metadata. Remaining 25 perturbable entries are clean operating setpoints (T, P, ΔP, duty, efficiency, RR, tolerances).
- ✓ **Storage Tank → thermal_oil** (architect override; rule: topology wins over PP metadata).
- ✓ **Reboiler Duty energy stream → petroleum** (architect override; rule: energy streams at subsystem hand-off classified by name/convention).

(none open)
