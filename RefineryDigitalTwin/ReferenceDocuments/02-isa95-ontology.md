# 02 — ISA-95 Ontology for the CDU Digital Twin

**Status:** Frozen
**Last review:** [date]

## 1. Why ISA-95

ISA-95 is the international standard for the integration of enterprise and control systems. It defines a hierarchical model of manufacturing operations that maps cleanly to digital-twin levels. Every JD targeting a process-manufacturing AI architect role expects fluency here; the JD lists it explicitly.

We use ISA-95 Part 1 (Models) and Part 2 (Object Model Attributes) as the basis. ISA-88 (batch-process control) is referenced for the column phase logic but not implemented in detail (CDU is continuous, not batch).

## 2. Hierarchy

```
Enterprise: AcmeRefining
└── Site: GulfCoastRefinery
    └── Area: Crude Distillation Area
        └── Process Cell / Unit: CDU-1
            ├── Equipment Module: PreheatTrain
            │   ├── Heat Exchanger: E-101
            │   ├── Heat Exchanger: E-102
            │   └── Charge Pump: P-100
            ├── Equipment Module: FiredHeater
            │   └── Heater: H-101
            ├── Equipment Module: Column
            │   ├── Column: C-101
            │   ├── Reflux Pump: P-101
            │   └── Overhead Condenser: E-110
            └── Equipment Module: ProductPumps
                ├── Kerosene Pump: P-102
                ├── Diesel Pump: P-103
                └── Residue Pump: P-104
```

This maps directly to four twin levels:

| ISA-95 level | Twin level | Example |
|---|---|---|
| Enterprise | Enterprise twin | Refinery KPIs, blended yield |
| Site / Area | Network twin | Inter-unit flow, product distribution |
| Process Cell / Unit | Plant twin | CDU process state, mass balance |
| Equipment Module / Equipment | Asset twin | H-101 health, P-100 RUL |

## 3. Entity model (canonical attributes)

Every node in the hierarchy carries:

```yaml
id: string                    # globally unique, dotted notation
type: enum                    # Enterprise|Site|Area|Unit|EquipmentModule|Equipment
parent_id: string | null
display_name: string
description: string
classification:
  isa95_level: int            # 0=process, 1=field, 2=control, 3=ops, 4=enterprise
  iso14224_class: string      # e.g., "rotating-equipment.pump.centrifugal"
location:
  site_grid_ref: string
  p_and_id_ref: string        # links to P&ID drawing reference
operational_state: enum       # Running|Idle|Faulted|Maintenance|Off
tags:                         # references to PLC/OPC-UA tags
  - tag_id: string
    role: enum                # InputPV|OutputPV|Setpoint|Alarm|Status
    units: string
relationships:
  - type: enum                # FeedsInto|RecoversHeatFrom|ControlledBy|MonitoredBy
    target_id: string
metadata:
  manufacturer: string
  model: string
  install_date: date
  expected_life_years: number
```

## 4. Equipment classes (refinery-specific)

Each equipment class extends the canonical entity with class-specific attributes. We use ISO 14224 taxonomy for compatibility with reliability industry standards.

### 4.1 Centrifugal pump

```yaml
class: rotating-equipment.pump.centrifugal
attributes:
  rated_flow_m3h: number
  rated_head_m: number
  rated_power_kw: number
  motor_voltage_v: number
  driver_type: enum           # Motor|Turbine|Engine
  duty: enum                  # Continuous|Intermittent|Standby
key_tags:                     # what every pump must expose
  - role: InputPV; meaning: SuctionPressure
  - role: InputPV; meaning: DischargePressure
  - role: InputPV; meaning: FlowRate
  - role: InputPV; meaning: VibrationOverall
  - role: InputPV; meaning: BearingTemperature
  - role: Status; meaning: RunStatus
  - role: Alarm;  meaning: HighVibration
failure_modes:                # per ISO 14224
  - cavitation
  - bearing_failure
  - seal_leak
  - impeller_wear
```

### 4.2 Fired heater

```yaml
class: static-equipment.fired-heater.atmospheric
attributes:
  duty_mw: number
  passes: integer
  fuel_type: enum             # Gas|Oil|DualFuel
  draft_type: enum            # Natural|Forced|Induced|Balanced
key_tags:
  - role: InputPV; meaning: PassOutletTemp1
  - role: InputPV; meaning: PassOutletTemp2
  - role: InputPV; meaning: PassOutletTemp3
  - role: InputPV; meaning: PassOutletTemp4
  - role: InputPV; meaning: FuelGasFlow
  - role: InputPV; meaning: FuelGasPressure
  - role: InputPV; meaning: StackO2
  - role: InputPV; meaning: StackTemp
  - role: InputPV; meaning: ArchDraft
  - role: Alarm;  meaning: HighSkinTemp
failure_modes:
  - tube_fouling
  - tube_rupture
  - flame_impingement
  - convection_section_fouling
```

### 4.3 Distillation column

```yaml
class: static-equipment.column.distillation.atmospheric
attributes:
  trays: integer
  diameter_m: number
  height_m: number
  feed_tray: integer
  side_draws:
    - tray: integer
      product: string
key_tags:
  - role: InputPV; meaning: TopTemp
  - role: InputPV; meaning: BottomTemp
  - role: InputPV; meaning: FeedTemp
  - role: InputPV; meaning: TopPressure
  - role: InputPV; meaning: DifferentialPressure
  - role: InputPV; meaning: RefluxFlow
  - role: InputPV; meaning: Tray*Temp        # parametric
  - role: Alarm;  meaning: HighDP             # flooding indicator
failure_modes:
  - flooding
  - weeping
  - tray_fouling
  - feed_distributor_failure
```

### 4.4 Heat exchanger (shell-and-tube)

```yaml
class: static-equipment.heat-exchanger.shell-and-tube
attributes:
  duty_mw: number
  area_m2: number
  shell_passes: integer
  tube_passes: integer
  hot_side_fluid: string
  cold_side_fluid: string
key_tags:
  - role: InputPV; meaning: HotInletTemp
  - role: InputPV; meaning: HotOutletTemp
  - role: InputPV; meaning: ColdInletTemp
  - role: InputPV; meaning: ColdOutletTemp
  - role: InputPV; meaning: HotPressureDrop
failure_modes:
  - tube_fouling
  - tube_leak
  - tube_plugging
```

### 4.5 Control valve

```yaml
class: instrumentation.control-valve
attributes:
  cv_max: number
  fail_position: enum         # Open|Closed|Last
  characteristic: enum        # Linear|EqualPercent|QuickOpen
key_tags:
  - role: Setpoint; meaning: PositionSP
  - role: OutputPV; meaning: PositionPV
  - role: Status;   meaning: TravelDeviation
failure_modes:
  - stuck
  - hunting
  - actuator_failure
  - seat_leak
```

## 5. Tag naming convention

Every simulated tag follows this pattern:

```
{site}.{unit}.{equipment_id}.{measurement}
```

Example: `GulfCoast.CDU1.H-101.PassOutletTemp1`

For PLC namespace compatibility, the same tag is also exposed under:

- Allen-Bradley: `Program:CDU1.H101.PassOutletTemp1`
- Siemens S7: `DB10.DBD8` (mapped via tag dictionary)
- OPC-UA: `ns=2;s=GulfCoast.CDU1.H-101.PassOutletTemp1`

The tag dictionary lives at `docs/ontology/tag-dictionary.json` and is the source of truth for all naming.

## 6. Relationships and the network twin

The network twin is built from `relationships` arrays on each entity. Common relationship types:

- `FeedsInto` — material flow direction (E-102 → H-101 → C-101)
- `RecoversHeatFrom` — heat integration links
- `ControlledBy` — control valve to controlled variable
- `MonitoredBy` — transmitter to equipment
- `Bypasses` — bypass paths around equipment
- `IsRedundantWith` — A/B equipment pairs

Drawn as a directed graph, this gives the network twin its topology. Used by:
- The dashboard map view (auto-layout)
- The simulation engine (propagation rules)
- The reliability agent (impact analysis: "if P-100 fails, what's downstream?")

## 7. Files

| File | Contents |
|---|---|
| `docs/ontology/enterprise.json` | Enterprise + site + area nodes |
| `docs/ontology/cdu-plant-twin.json` | CDU unit + equipment modules |
| `docs/ontology/equipment/*.json` | Per-equipment instances (E-101, H-101, etc.) |
| `docs/ontology/tag-dictionary.json` | All tags: canonical name, AB name, Siemens DB ref, OPC-UA NodeId |
| `docs/ontology/equipment-classes.json` | Class definitions (pump, heater, column, etc.) |
| `docs/ontology/relationships.json` | Edge list for network twin |

These JSON files are consumed by:
- The simulator (which equipment to model)
- The OPC-UA server (which tags to expose)
- The Twin Ontology Service (the truth source)
- The dashboard (map layout, asset cards)
- The MCP tools (entity lookups)

## 8. Extending to other industries

To extend to petrochemicals: add `class: static-equipment.reactor.fixed-bed`, `class: static-equipment.column.extractive-distillation`. The hierarchy remains identical.

To extend to discrete manufacturing: replace process cells with work cells, equipment modules with workstations. The four-tier twin model holds; only equipment classes change.

This proves the "reusable, multi-industry foundation" claim by construction, not by assertion.
