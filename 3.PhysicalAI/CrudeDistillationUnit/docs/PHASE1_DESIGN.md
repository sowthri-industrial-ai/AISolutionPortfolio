# Phase 1 Design — CDU Scene in Kit

**Status:** Design locked 2026-05-09
**Execution:** Pending AWS Mumbai g6.xlarge capacity return
**Charter reference:** §6 (CDU scope, ISA-95 hierarchy, 3-layer USD)

---

## 1. Scope

Build a 3D scene of one Crude Distillation Unit (CDU) in NVIDIA Omniverse Kit, using simple primitive geometry, proper USD layer composition, ISA-95 hierarchy, and Unified Namespace (UNS) data structure.

This is a **generic CDU model**. Not based on any specific real refinery. The model demonstrates the digital twin pattern at a level of detail appropriate for a portfolio piece.

---

## 2. Equipment selected

Five pieces composing a simplified CDU process flow:

| # | Equipment | ISA-95 ID | Geometry primitive | Approximate dimensions |
|---|---|---|---|---|
| 1 | Furnace | F101 | Box + smaller box on top (stack) | 8m × 8m × 12m + 2m × 2m × 8m stack |
| 2 | Distillation column | T101 | Tall vertical cylinder | 4m diameter × 40m tall |
| 3 | Heat exchanger 1 | E101 | Horizontal cylinder | 8m long × 1.5m diameter |
| 4 | Heat exchanger 2 | E102 | Horizontal cylinder | 8m long × 1.5m diameter |
| 5 | Pump | P101 | Compact box | 1.5m × 1m × 1.5m |

**Why these five:** Standard educational simplification of a CDU. Universally recognizable to process engineers. Geometric variety (tall thin, horizontal cylinder, squat box, small) provides good portfolio breadth without CAD complexity.

**Process flow story (for interview narration):**
Crude oil enters the **Pump (P101)** which moves it through **Heat Exchanger E101** (preheats with hot products), then through the **Furnace (F101)** (heats to ~370°C), into the **Distillation Column (T101)** (separates into fractions), with hot products exiting through **Heat Exchanger E102** (recovers heat).

---

## 3. Layout

All 5 equipment pieces in one scene. Distillation column central; other equipment grouped around it (matching real refinery physical layouts).

**Approximate positions** (column at origin; Y is vertical/up):

```
Furnace_F101:        ( 15, 0,  10)   — east of column
Column_T101:         (  0, 0,   0)   — origin (centerpiece)
HeatExchanger_E101:  (-12, 0,   8)   — west of column
HeatExchanger_E102:  (-12, 0,  -8)   — west, opposite side
Pump_P101:           (-18, 0,   0)   — far west of column
```

Final positions can shift during scene authoring; this is a starting layout.

---

## 4. ISA-95 naming hierarchy

Three-level hierarchy: **Site → Area → Equipment**.

```
/RefinerySiteA
    /CDU_01
        /Furnace_F101
        /Column_T101
        /HeatExchanger_E101
        /HeatExchanger_E102
        /Pump_P101
```

**Naming conventions:**
- Equipment letter codes follow petrochemical industry standards: F = Furnace, T = Tower (distillation column), E = Exchanger, P = Pump
- Number `101` indicates "first instance of this equipment type in this unit"
- All paths lowercase-separator-friendly (no spaces, no special chars except underscore)

These paths become the USD prim paths in Kit. `xformOp:translate` on each prim sets its position.

---

## 5. Unified Namespace (UNS) topic structure

UNS extends ISA-95 with an Enterprise level and adds parameters at the leaves. Used for industrial data publishing (typically MQTT or OPC-UA).

**Top-level enterprise:** `RefineryEnterprise`

**Topic structure:**
```
RefineryEnterprise/RefinerySiteA/CDU_01/{Equipment}/{parameter}
```

**Total parameters:** 22 across 5 equipment pieces.

### Per-equipment parameters

**Furnace_F101** (4 parameters)
| Parameter | Topic | Unit |
|---|---|---|
| Inlet temperature | `RefineryEnterprise/RefinerySiteA/CDU_01/Furnace_F101/inlet_temperature` | °C |
| Outlet temperature | `RefineryEnterprise/RefinerySiteA/CDU_01/Furnace_F101/outlet_temperature` | °C |
| Fuel flow | `RefineryEnterprise/RefinerySiteA/CDU_01/Furnace_F101/fuel_flow` | kg/h |
| Status | `RefineryEnterprise/RefinerySiteA/CDU_01/Furnace_F101/status` | enum |

**Column_T101** (5 parameters)
| Parameter | Topic | Unit |
|---|---|---|
| Top pressure | `RefineryEnterprise/RefinerySiteA/CDU_01/Column_T101/top_pressure` | kPa |
| Bottom pressure | `RefineryEnterprise/RefinerySiteA/CDU_01/Column_T101/bottom_pressure` | kPa |
| Top temperature | `RefineryEnterprise/RefinerySiteA/CDU_01/Column_T101/top_temperature` | °C |
| Bottom temperature | `RefineryEnterprise/RefinerySiteA/CDU_01/Column_T101/bottom_temperature` | °C |
| Feed rate | `RefineryEnterprise/RefinerySiteA/CDU_01/Column_T101/feed_rate` | m³/h |

**HeatExchanger_E101** (4 parameters)
| Parameter | Topic | Unit |
|---|---|---|
| Hot inlet temperature | `RefineryEnterprise/RefinerySiteA/CDU_01/HeatExchanger_E101/hot_inlet_temp` | °C |
| Hot outlet temperature | `RefineryEnterprise/RefinerySiteA/CDU_01/HeatExchanger_E101/hot_outlet_temp` | °C |
| Cold inlet temperature | `RefineryEnterprise/RefinerySiteA/CDU_01/HeatExchanger_E101/cold_inlet_temp` | °C |
| Cold outlet temperature | `RefineryEnterprise/RefinerySiteA/CDU_01/HeatExchanger_E101/cold_outlet_temp` | °C |

**HeatExchanger_E102** (4 parameters — same structure as E101)
| Parameter | Topic | Unit |
|---|---|---|
| Hot inlet temperature | `RefineryEnterprise/RefinerySiteA/CDU_01/HeatExchanger_E102/hot_inlet_temp` | °C |
| Hot outlet temperature | `RefineryEnterprise/RefinerySiteA/CDU_01/HeatExchanger_E102/hot_outlet_temp` | °C |
| Cold inlet temperature | `RefineryEnterprise/RefinerySiteA/CDU_01/HeatExchanger_E102/cold_inlet_temp` | °C |
| Cold outlet temperature | `RefineryEnterprise/RefinerySiteA/CDU_01/HeatExchanger_E102/cold_outlet_temp` | °C |

**Pump_P101** (4 parameters — note: 4 not 5)
| Parameter | Topic | Unit |
|---|---|---|
| Flow rate | `RefineryEnterprise/RefinerySiteA/CDU_01/Pump_P101/flow_rate` | m³/h |
| Suction pressure | `RefineryEnterprise/RefinerySiteA/CDU_01/Pump_P101/suction_pressure` | kPa |
| Discharge pressure | `RefineryEnterprise/RefinerySiteA/CDU_01/Pump_P101/discharge_pressure` | kPa |
| Status | `RefineryEnterprise/RefinerySiteA/CDU_01/Pump_P101/status` | enum |

**Total:** 4 + 5 + 4 + 4 + 4 = **21 parameters** (one fewer than initially estimated; final count locked).

### Phase 3 binding plan

Charter §6 specifies 10 OPC-UA tags for Phase 3 live data binding. Selection priority (most demo-relevant first):

1. `Column_T101/top_temperature`
2. `Column_T101/bottom_temperature`
3. `Column_T101/top_pressure`
4. `Column_T101/feed_rate`
5. `Furnace_F101/outlet_temperature`
6. `Furnace_F101/fuel_flow`
7. `HeatExchanger_E101/hot_outlet_temp`
8. `HeatExchanger_E102/hot_outlet_temp`
9. `Pump_P101/flow_rate`
10. `Pump_P101/discharge_pressure`

These 10 cover the full process flow narrative (pump → exchanger → furnace → column) and demonstrate temperature, pressure, and flow data types.

The remaining 11 parameters are defined in the metadata layer for completeness but not bound to live data.

---

## 6. USD layer structure

Three sublayers composed by a top-level scene file. Charter §6 requirement.

**File structure:**
```
RefineryTwin/
└── asset-library/
    └── cdu_demo/
        ├── cdu_demo.usd          ← top-level, references the 3 below
        ├── cdu_geometry.usda     ← geometry layer
        ├── cdu_materials.usda    ← materials layer
        └── cdu_metadata.usda     ← metadata layer (UNS topics, OPC-UA refs)
```

### Layer 1 — Geometry (`cdu_geometry.usda`)

Holds:
- Prim hierarchy under `/RefinerySiteA/CDU_01/...`
- Each equipment as a `Mesh` or `Cube`/`Cylinder` primitive
- Transforms (`xformOp:translate`, `xformOp:scale`)
- Bounding boxes
- No materials, no textures, no metadata beyond prim paths

Owned by: mechanical engineering (in real workflows).

### Layer 2 — Materials (`cdu_materials.usda`)

Holds:
- `Material` prims under `/Looks/...`
- USD Preview Surface shaders
- Material bindings to geometry prims (via `material:binding` relationship)
- Initial materials simple — flat colors, basic metallic settings:
  - Furnace: dark gray (steel)
  - Column: light gray (insulated steel)
  - Heat exchangers: medium gray with green accent (typical refinery color)
  - Pump: dark teal/green (typical equipment color)
- Future-extensibility: this layer can be swapped for thermal-imaging style, X-ray view, etc.

Owned by: visualization team (in real workflows).

### Layer 3 — Metadata (`cdu_metadata.usda`)

Holds (as USD custom attributes on each equipment prim):
- `customLayerData:uns_topic_prefix` — full UNS path (e.g., `RefineryEnterprise/RefinerySiteA/CDU_01/Column_T101`)
- `customLayerData:isa95_path` — ISA-95 hierarchical path
- `customLayerData:opcua_node_ids` — list of OPC-UA node IDs (placeholders until Phase 3)
- `customLayerData:equipment_type` — type code (Furnace, Column, HeatExchanger, Pump)
- `customLayerData:tag_id` — equipment ID (F101, T101, etc.)
- `customLayerData:parameters` — list of parameter names with units

Owned by: automation/process engineers (in real workflows).

### Top-level (`cdu_demo.usd`)

A small file that references the three sublayers in order. Kit opens this file; it composes everything underneath. ASCII format (`.usd` saves as ASCII by default in Kit Base Editor; can be saved as `.usdc` binary for performance later if needed).

---

## 7. Execution checklist (when AWS capacity returns)

Order of operations for the actual Phase 1 build session:

### Story 1.1 — Scene scaffold (30 min)
- [ ] Start AWS instance, verify capacity, SSH in
- [ ] Restart Xvfb + x11vnc + websockify on cloud
- [ ] SSH tunnel from Mac, open noVNC in browser
- [ ] Launch Kit
- [ ] Create new USD file in Kit: `cdu_demo.usd`
- [ ] Create three sublayers: `cdu_geometry.usda`, `cdu_materials.usda`, `cdu_metadata.usda`
- [ ] Save and verify all four files exist on cloud filesystem

### Story 1.2 — Distillation column (30 min)
- [ ] In geometry layer: create `Cylinder` prim at `/RefinerySiteA/CDU_01/Column_T101`
- [ ] Set dimensions: 4m diameter, 40m tall
- [ ] Position at origin (0, 0, 0) with column axis up
- [ ] Verify renders correctly in viewport
- [ ] Save

### Story 1.3 — Remaining equipment (45 min)
- [ ] Furnace_F101: box at (15, 0, 10) with stack on top
- [ ] HeatExchanger_E101: horizontal cylinder at (-12, 0, 8)
- [ ] HeatExchanger_E102: horizontal cylinder at (-12, 0, -8)
- [ ] Pump_P101: compact box at (-18, 0, 0)
- [ ] Verify all 5 equipment visible in viewport
- [ ] Save

### Story 1.4 — Materials (30 min)
- [ ] In materials layer: create 4-5 USD Preview Surface materials
- [ ] Assign materials to equipment prims
- [ ] Verify shading visible in viewport
- [ ] Save

### Story 1.5 — Metadata (30 min)
- [ ] In metadata layer: add custom attributes to each equipment prim:
  - `uns_topic_prefix` (full UNS path)
  - `isa95_path`
  - `equipment_type`, `tag_id`
  - `parameters` (list)
- [ ] Save

### Story 1.6 — Snapshot + commit (15 min)
- [ ] Verify all 4 USD files exist on cloud
- [ ] Copy files from cloud to Mac via `scp` (we'll script this)
- [ ] Commit to GitHub: `phase-1: CDU scene with USD 3-layer composition`
- [ ] Stop AWS instance
- [ ] Update OPERATOR_RUNBOOK.md

**Phase 1 total estimated time:** ~3 hours of cloud session work + ~30 min of design refinement during execution.

---

## 8. Why these choices

**On primitive geometry over CAD models:** Charter scope is "demonstrate the digital twin pattern, not photorealistic modeling." Primitives keep the focus on USD composition, ISA-95 structure, and data binding — which is what Omniverse engineers actually do.

**On 3 layers over 1:** Demonstrates real-world workflow patterns. In a 30-second interview moment, you can swap the materials layer to a thermal style and the geometry/metadata stays untouched. That's a defining Omniverse capability.

**On UNS over plain ISA-95:** Modern industrial automation pairs ISA-95 (structure) with UNS (data publishing). Knowing both signals current industry awareness, not just textbook knowledge.

**On 21 parameters defined / 10 bound:** Defining more shows depth ("this scene knows about 21 parameters"). Binding 10 shows execution discipline ("we delivered exactly what charter specified"). Both stories are good for an interview.

**On generic naming (RefinerySiteA, no real refinery):** Avoids implying authorized association with any specific company. Keeps the portfolio piece defensible.

---

## 9. Open questions (deferred to execution)

These are minor decisions that can be made during execution without blocking design:

- **Final material colors** — initial proposals are conservative; can be tuned for visual appeal during Story 1.4.
- **Exact prim hierarchy under each equipment** — whether to nest sub-meshes (e.g., Furnace has a body prim and a stack prim as children) or flat structure.
- **Coordinate system orientation** — Z-up (CAD/industrial standard) vs Y-up (Kit default). Will pick during Story 1.1 based on Kit's defaults; can convert later if needed.
- **Reference scale** — whether to scale equipment to real-world size (40m column) or simplify to 1/10 scale for camera framing during demo recording.

---

## 10. Charter compliance check

| Charter requirement (§6) | Phase 1 design |
|---|---|
| 1 CDU at "the refinery" | ✅ One CDU, generic site naming |
| 5 equipment pieces | ✅ Furnace, column, 2 heat exchangers, pump |
| 3-layer USD composition | ✅ Geometry, materials, metadata |
| ISA-95 hierarchy | ✅ Site → Area → Equipment with industry-standard codes |
| 10 OPC-UA tags (Phase 3) | ✅ 10 prioritized for binding (subset of 21 defined) |
| Custom Kit extension `com.sowthri.cdutwin` | ⏭️ Phase 2 |
| Isaac Sim scenarios (gas leak, rover, valve) | ⏭️ Phase 4 |

Phase 1 design is fully charter-compliant.

---

**Document status:** Locked design, ready to execute when AWS Mumbai capacity returns.

**Next step:** Begin Story 1.1 execution upon successful instance start.
