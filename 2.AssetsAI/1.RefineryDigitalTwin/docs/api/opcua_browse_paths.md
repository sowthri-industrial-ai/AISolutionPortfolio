# OPC-UA Browse Paths — Refinery Digital Twin

Sample browse paths for the Stage 4 server at `opc.tcp://localhost:4840/refinery_twin/`.

The OPC-UA namespace index for the custom `Refinery/` tree is **`2`** (asyncua
auto-assigns: 0 = OPC-UA built-ins, 1 = server-local, 2 = our custom namespace
`urn:RefineryDigitalTwin`). All custom paths use the `2:` prefix.

## Top-level structure

```
0:Objects/
└── 2:Refinery/
    ├── 2:PetroleumSide/
    │   ├── 2:MaterialStreams/
    │   ├── 2:EnergyStreams/
    │   └── 2:Columns/
    ├── 2:ThermalOilLoop/
    │   ├── 2:MaterialStreams/
    │   ├── 2:EnergyStreams/
    │   └── 2:Equipment/
    └── 2:StreamerHealth/
        ├── 2:LastSnapshotCycle    (Int32)
        ├── 2:LastSnapshotTimestamp (String)
        └── 2:Stage2Running         (Boolean)
```

Owner-level browse names match the Phase 0a tag dictionary's tag-ID prefix
(e.g., `MS-OIL`, `ES-CONDENSER_DUTY`, `COL-DISTILLATION_COLUMN`). Hyphens are
preserved.

## Canonical sample paths (operator demos)

Paths below are OPC-UA browse-path lists (suitable for `client.nodes.root.get_child([...])`).
For UaExpert, paste into the address bar of "Go to Node" or drag from the
Address Space tree.

### Petroleum side

```
0:Objects / 2:Refinery / 2:PetroleumSide / 2:MaterialStreams / 2:MS-OIL / 2:OVERALL / 2:PROP_MS_0
    → Oil feed Temperature (K), overall phase

0:Objects / 2:Refinery / 2:PetroleumSide / 2:MaterialStreams / 2:MS-OIL / 2:OVERALL / 2:PROP_MS_2
    → Oil feed Mass Flow (kg/s) — Phase 0a ground truth ~41.03

0:Objects / 2:Refinery / 2:PetroleumSide / 2:MaterialStreams / 2:MS-OIL / 2:VAPOR / 2:PROP_MS_2
    → Oil feed Mass Flow (vapor phase, ~17% of overall)

0:Objects / 2:Refinery / 2:PetroleumSide / 2:MaterialStreams / 2:MS-OIL / 2:OVERALL / 2:MoleFraction / 2:PSE_3165_27
    → Mole fraction of PSE_3165_27 in Oil feed (overall phase)

0:Objects / 2:Refinery / 2:PetroleumSide / 2:EnergyStreams / 2:ES-CONDENSER_DUTY / 2:EnergyFlow
    → Condenser Duty (kW) — Phase 0a ground truth ~29755.28 kW (29.76 MW)

0:Objects / 2:Refinery / 2:PetroleumSide / 2:EnergyStreams / 2:ES-REBOILER_DUTY / 2:EnergyFlow
    → Reboiler Duty (kW) — Phase 0a ground truth ~-27275 kW

0:Objects / 2:Refinery / 2:PetroleumSide / 2:Columns / 2:COL-DISTILLATION_COLUMN / 2:RefluxRatio
    → Reflux ratio — Phase 0a ground truth ~2.499

0:Objects / 2:Refinery / 2:PetroleumSide / 2:Columns / 2:COL-DISTILLATION_COLUMN / 2:STAGE_3 / 2:T_K
    → Distillation Column, Stage 3 temperature (K)
```

### Thermal oil loop

```
0:Objects / 2:Refinery / 2:ThermalOilLoop / 2:MaterialStreams / 2:MS-THERMINOL_VP1 / 2:PROP_MS_2
    → Therminol VP1 mass flow (kg/s) — Phase 0a ground truth 200.0

0:Objects / 2:Refinery / 2:ThermalOilLoop / 2:EnergyStreams / 2:ES-HEATING_DUTY / 2:EnergyFlow
    → Thermal-oil-side Heating Duty (kW)

0:Objects / 2:Refinery / 2:ThermalOilLoop / 2:Equipment / 2:PMP-THERMAL_OIL_PUMP / 2:Efficiency
    → Thermal oil pump efficiency (%)

0:Objects / 2:Refinery / 2:ThermalOilLoop / 2:Equipment / 2:HC-THERMAL_OIL_HEATING / 2:OutletTemperature
    → Thermal oil heater outlet T (K)

0:Objects / 2:Refinery / 2:ThermalOilLoop / 2:Equipment / 2:TANK-THERMINOL_VP1_STORAGE_TANK / 2:Volume
    → Therminol VP1 Storage Tank volume
```

### StreamerHealth (system monitoring)

```
0:Objects / 2:Refinery / 2:StreamerHealth / 2:LastSnapshotCycle
    → Cycle number of most recent ingested snapshot (Int32)

0:Objects / 2:Refinery / 2:StreamerHealth / 2:LastSnapshotTimestamp
    → ISO 8601 timestamp of most recent ingested snapshot (String)

0:Objects / 2:Refinery / 2:StreamerHealth / 2:Stage2Running
    → True while Stage 2 streamer is writing to an active hour file (Boolean)
```

## Client-specific tips

### asyncua Python client

```python
async with Client(ENDPOINT) as client:
    node = await client.nodes.root.get_child([
        "0:Objects", "2:Refinery", "2:PetroleumSide",
        "2:EnergyStreams", "2:ES-CONDENSER_DUTY", "2:EnergyFlow",
    ])
    val = await node.read_value()
```

### UaExpert

1. Connect to `opc.tcp://localhost:4840/refinery_twin/` with security `None — None`,
   anonymous.
2. In **Address Space**, expand `Objects → Refinery → ...` and drag any leaf
   node into the **Data Access** view. Value updates as Stage 2 ingests new
   snapshots (every ~30 s).
3. For subscriptions, UaExpert auto-creates one when you drag a node. Default
   publish interval is 1000 ms (1 s); per-node change-notification will fire
   immediately after the next Stage 2 solve cycle.

### KEPServerEX / Ignition / generic SCADA

Most SCADA clients expose OPC-UA browse via a tree picker. Point them at
`opc.tcp://localhost:4840/refinery_twin/` with anonymous + no security; the
browse tree above appears under `Objects → Refinery`. Drag/select leaf nodes
into the SCADA's tag database; subscriptions are handled by the client.

## NodeId vs BrowsePath

The browse-path notation above (`0:Objects/2:Refinery/...`) is portable across
OPC-UA clients. Some clients use NodeIds instead — asyncua creates the
NodeIds with auto-incremented integers in namespace 2, so they're not stable
across server restarts. **Always use browse paths in scripts**, not NodeIds.

## What about identifier persistence?

NodeIds are auto-assigned on server boot. If a client caches a NodeId between
sessions, it can break on restart. Mitigation:

- Use browse paths (above) — always stable as long as the tag dictionary
  doesn't change.
- If a downstream tool absolutely needs stable NodeIds, switch
  `add_variable(nodeid=...)` from auto-assigned to explicit (e.g.,
  `nodeid=ua.NodeId("MS-OIL.OVERALL.PROP_MS_0", 2)` string identifier in our
  namespace). Not a Wave-1.5 / A2 deliverable; flag for post-demo hardening if
  a downstream SCADA needs it.
