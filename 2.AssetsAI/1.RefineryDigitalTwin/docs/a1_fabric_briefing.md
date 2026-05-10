# A1 Briefing — Feature 1 (Microsoft Fabric Ingestion) + Stage 5 (Event Hubs Producer)

**Project:** Refinery Digital Twin · F1 cloud milestone + tenant foundation
**Issued by:** Architect chat
**Implementer:** Claude Code (implementation work) + Operator (tenant + license + Fabric portal work)
**Operator:** Sowthri
**Status:** Phase 2 closed → this briefing
**Branch:** `phase-3-fabric` (per portfolio convention)
**Estimated effort:** ~30 min operator one-time setup + ~2-3 days Claude Code implementation, runs in parallel

---

## Goal

Get DWSIM snapshot data flowing from Sowthri's Mac to Microsoft Fabric, queryable via KQL, and visible in a basic Real-Time Dashboard. This is the **first cloud-facing milestone** — the moment the demo stops being "Sowthri's Mac" and becomes "Azure-native digital twin."

A1 covers two coupled pieces:
1. **Stage 5 — Event Hubs producer** (local Python, tails the Stage 2 JSONL stream and pushes to Azure Event Hubs)
2. **Feature 1 — Fabric ingestion** (Eventstream consumes Event Hubs, lands in Eventhouse / KQL database, basic Real-Time Dashboard)

Plus the operator-driven prerequisite: a new Microsoft Entra tenant + Power BI Pro license + Azure access grant, since Fabric requires a work-or-school account that the operator's personal Microsoft account doesn't satisfy.

A2 (Stages 3 + 4 — REST API + OPC-UA, local protocols) follows A1.

## Why this matters

After A1 lands:
- Live refinery simulation data flowing into Azure, queryable in real-time
- Cloud-side visualization (basic charts in Real-Time Dashboard — reboiler duty, condenser duty, Therminol mass flow, etc.)
- Anyone with portal permissions can view the dashboard remotely
- Foundation for F2 (twin ontology) and F3 (agents) — both consume Eventhouse data
- Demo narrative shifts from "look at Stage 2 working locally" to "Microsoft Fabric is ingesting the simulation"
- Brand match: portfolio narrative uses "Microsoft Fabric data fabric" — A1 makes this true

## Inputs

| | Default | |
|---|---|---|
| Substrate | (locked, same as all prior phases) | |
| Stage 2 streamer | running, producing JSONL at `4.snapshots/stage2/stream_*.jsonl` | source for Stage 5 producer |
| Phase 1 infra | RG `rg-refinerydigitaltwin-dev`, Static Web App, deploy.yml | extended in A1 |
| Operator account (work) | TBD — created in operator setup | needed for Fabric portal |
| Operator account (personal) | existing Azure subscription owner | unchanged |
| Cycle interval | 30 s (inherited from Stage 2) | not touched |
| Demo region | swedencentral (RG), westeurope (SWA, fallback for Free SKU) | new resources land in swedencentral |

## Required reading

1. `docs/DWSIM_KNOWLEDGE_BASE.md` — bug classes still apply
2. `docs/STREAMING_PLAN.md` — Part C, Stage 5 expectations
3. `2.automation/stage2/streamer.py` — reference for tail-reading patterns and rotation handling
4. `3.probes/phase0a/phase0a_findings.md` — tag dictionary semantics (correct path)
5. `infra/main.bicep` + `infra/azure.yaml` — Phase 1 infra patterns to extend
6. This briefing — the contract

## Toolchain

- Same x86 venv for the Stage 5 producer (`2.automation/.venv-x86/`)
- New dependency for Stage 5: `azure-eventhub` Python SDK (~10 MB, pure Python wheels)
- Bicep CLI / azd (already in place from Phase 1)
- Azure CLI (`az`) for tenant operations and role assignments
- Microsoft Fabric portal (operator-driven; manual setup of workspace + Eventstream + Eventhouse)

## Project layout context

```
~/Documents/AISolutionPortfolio/2.AssetsAI/1.RefineryDigitalTwin/
├── docs/
│   ├── a1_fabric_briefing.md            ← this briefing
│   ├── runbooks/
│   │   └── tenant_setup.md              ← NEW operator runbook (you author)
│   └── kql/                             ← NEW Eventhouse query library
│       ├── reboiler_duty_timeseries.kql
│       ├── condenser_duty_timeseries.kql
│       └── tag_extraction_pattern.kql
├── 2.automation/
│   ├── stage1/, stage2/                 (read-only, prior stages)
│   └── stage5/                          ← NEW
│       ├── producer.py                  ← Event Hubs producer
│       └── position.json                ← runtime tail position state (gitignored)
├── 4.snapshots/
│   └── stage2/                          (input for Stage 5 producer)
├── infra/
│   ├── main.bicep                       (extended)
│   ├── modules/
│   │   ├── staticwebapp.bicep           (existing)
│   │   ├── eventhub.bicep               ← NEW
│   │   └── fabric_capacity.bicep        ← NEW
│   ├── azure.yaml                       (no change)
│   └── main.parameters.json             (extended with capacity-admin email)
└── .github/workflows/
    └── deploy.yml                       (extended: resume/pause actions)
```

---

## Part A — Operator one-time setup (Sowthri's domain, ~30 min)

These steps cannot be automated (privileged Microsoft 365 / payment / first-sign-in actions). The operator does them, and Claude Code's implementation assumes they're complete.

Output: a runbook at `docs/runbooks/tenant_setup.md` capturing what was done so the work is reproducible.

### Step A1 — Create new Microsoft Entra tenant (~5 min)

In your existing Azure portal (signed in with personal account):
- Search "Microsoft Entra ID" → click → "Manage tenants" → **Create**
- Tenant type: **Workforce**
- Organization name: e.g., `Sowthri Industrial AI`
- Initial domain: e.g., `sowthriindustrialai` → produces `sowthriindustrialai.onmicrosoft.com`
- Country: India (or operator's preferred region)
- Review → Create

✓ Success criterion: new tenant appears in "Manage tenants" list. Capture tenant ID for the runbook.

### Step A2 — Create admin user in new tenant (~2 min)

Top-right profile icon → "Switch directory" → switch to the new tenant.

In new tenant:
- Microsoft Entra ID → Users → **New user** → "Create user"
- User principal name: `sowthri` (or other; forms `<name>@<tenant-domain>.onmicrosoft.com`)
- Display name: operator's name
- Password: auto-generate (capture securely) or set
- Roles: **Global Administrator**
- Create

✓ Success criterion: user created. Sign-in details captured in runbook. (Password rotation post-A1 setup is recommended.)

### Step A3 — Buy Power BI Pro license & assign (~5-10 min, payment required)

Open https://admin.microsoft.com — sign in with the new admin account (first sign-in: change password, set up MFA).

- Billing → Purchase services → search **"Power BI Pro"** → Buy
- Quantity: 1, monthly billing
- Add payment method (credit card)
- Complete purchase
- Billing → Licenses → assign Power BI Pro to the new admin user

✓ Success criterion: license assigned, visible on user's profile. Recurring cost: $14/user/mo.

### Step A4 — Verify Fabric portal access (~2 min)

Sign out, then sign in to https://app.fabric.microsoft.com with the new work account.

✓ Success criterion: lands on Fabric home page with workspace selector and "Create" button visible.

✗ If still blocked: stop here and flag to architect. We pivot to F1b (ADX) before Claude Code starts.

### Step A5 — Grant new account access to existing Azure subscription (~5 min)

Switch back to personal-tenant Azure portal:

```bash
az login                                                    # personal account
az account set --subscription "<personal-sub-id>"

# Invite work account as guest
az ad user invite \
  --invited-user-email-address "sowthri@<tenant-domain>.onmicrosoft.com" \
  --invited-user-display-name "Sowthri (Work Account)" \
  --send-invitation-message true

# Grant Contributor on subscription
az role assignment create \
  --role Contributor \
  --assignee "sowthri@<tenant-domain>.onmicrosoft.com" \
  --scope "/subscriptions/<personal-sub-id>"

# Optional: also grant on the existing RG only (least privilege)
az role assignment create \
  --role Contributor \
  --assignee "sowthri@<tenant-domain>.onmicrosoft.com" \
  --scope "/subscriptions/<personal-sub-id>/resourceGroups/rg-refinerydigitaltwin-dev"
```

✓ Success criterion: work account can sign in to https://portal.azure.com (with Switch directory → personal tenant) and see the existing subscription with Contributor permissions.

### Step A6 — Author the runbook (~5 min)

Create `docs/runbooks/tenant_setup.md` capturing:
- New tenant ID (UUID)
- New tenant initial domain (e.g., `sowthriindustrialai.onmicrosoft.com`)
- Admin user UPN
- Power BI Pro purchase date and billing details
- Subscription role-assignment confirmation
- Date the setup was completed
- Cost recap: $14/user/mo recurring (Power BI Pro)

This runbook is checked into git on `phase-3-fabric`. Future readers see exactly what was provisioned and why.

✓ Part A done. Operator hands off to Claude Code with the new tenant ID and work account UPN as parameters for Bicep.

---

## Part B — Implementation work (Claude Code's domain)

Runs in parallel with Part A (Bicep can be written without the work account; provisioning waits for Part A's tenant ID).

### Behavior — Stage 5 Event Hubs producer

**File:** `2.automation/stage5/producer.py` (~250-350 lines)

**1. Bootstrap**
- Load `position.json` (or initialize if missing): `{ "current_file": null, "byte_offset": 0 }`
- Connect to Event Hub via `EventHubProducerClient.from_connection_string(connection_str, eventhub_name=...)` — connection string from environment variable `EVENT_HUB_CONNECTION_STRING`
- Open log file `producer.log` in append mode

**2. Main loop**

```python
while not shutdown:
    # Find current Stage 2 active hour file (newest stream_*.jsonl, NOT .gz)
    active_file = find_current_jsonl(stage2_dir)
    
    if active_file != position["current_file"]:
        # Stream rotated to a new hour file (or first start)
        position["current_file"] = active_file
        position["byte_offset"] = 0  # start from beginning of new file
    
    # Read new lines from byte_offset onward
    with open(active_file, "rb") as f:
        f.seek(position["byte_offset"])
        new_data = f.read()
    
    if not new_data:
        sleep(2)  # nothing new; gentle poll
        continue
    
    # Parse new lines (may be partial if last line is mid-write; defer it)
    lines = new_data.split(b"\n")
    if not new_data.endswith(b"\n"):
        complete_lines = lines[:-1]
        consumed_bytes = len(new_data) - len(lines[-1])
    else:
        complete_lines = lines[:-1]  # last element is empty after final \n
        consumed_bytes = len(new_data)
    
    # Filter empty lines, parse JSON for sanity, batch
    batch = producer_client.create_batch(max_size_in_bytes=900_000)  # ~900KB, leave Event Hubs headroom
    for line in complete_lines:
        if not line.strip():
            continue
        try:
            json.loads(line)  # parse-only validation
        except json.JSONDecodeError:
            log_warn(f"skipping malformed line at offset {position['byte_offset']}")
            continue
        try:
            batch.add(EventData(line))
        except ValueError:
            # Batch full; send and start new one
            producer_client.send_batch(batch)
            batch = producer_client.create_batch(max_size_in_bytes=900_000)
            batch.add(EventData(line))
    
    if len(batch) > 0:
        producer_client.send_batch(batch)
        position["byte_offset"] += consumed_bytes
        save_position(position)
    
    log_cycle(lines_sent=len(complete_lines), file=active_file, offset=position["byte_offset"])
    sleep(2)
```

**3. Schema sent to Event Hubs**

Each Event Hub message body = one JSONL line from Stage 2 = one snapshot. No transformation. Eventstream parses JSON downstream.

**4. Resilience**
- Event Hub send failure → exponential backoff (1s, 2s, 4s, 8s, max 30s); don't advance `byte_offset` until send succeeds
- 3 consecutive send-batch failures → exit non-zero (operator restarts)
- Position file write is atomic (temp + rename)

**5. Graceful shutdown**
- SIGINT/SIGTERM → finish current batch, save position, close producer, exit 0

### Behavior — Bicep updates

**`infra/modules/eventhub.bicep`** (new module)

```bicep
@description('Event Hubs namespace name')
param namespaceName string

@description('Event Hub instance name')
param eventHubName string

@description('Region')
param location string

@description('Tags')
param tags object = {}

resource ehns 'Microsoft.EventHub/namespaces@2024-01-01' = {
  name: namespaceName
  location: location
  tags: tags
  sku: {
    name: 'Basic'  // ~$11/mo, sufficient for ~120 events/hr
    tier: 'Basic'
    capacity: 1
  }
  properties: {
    isAutoInflateEnabled: false
    publicNetworkAccess: 'Enabled'
  }
}

resource eh 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = {
  parent: ehns
  name: eventHubName
  properties: {
    messageRetentionInDays: 1
    partitionCount: 1
  }
}

resource sendRule 'Microsoft.EventHub/namespaces/eventhubs/authorizationRules@2024-01-01' = {
  parent: eh
  name: 'producer-send'
  properties: {
    rights: ['Send']
  }
}

output eventHubNamespaceName string = ehns.name
output eventHubName string = eh.name
output sendRuleId string = sendRule.id
```

**`infra/modules/fabric_capacity.bicep`** (new module)

```bicep
@description('Fabric capacity name')
param name string

@description('Region')
param location string

@description('Tags')
param tags object = {}

@description('Email of work-account capacity admin (from Part A)')
param adminEmail string

resource capacity 'Microsoft.Fabric/capacities@2023-11-01' = {
  name: name
  location: location
  tags: union(tags, { 'azd-service-name': 'fabric' })
  sku: {
    name: 'F2'
    tier: 'Fabric'
  }
  properties: {
    administration: {
      members: [adminEmail]
    }
  }
}

output capacityId string = capacity.id
output capacityName string = capacity.name
```

**`infra/main.bicep`** — extend to invoke both new modules. Pass `adminEmail` as a parameter from `main.parameters.json`.

**`infra/main.parameters.json`** — add:
```json
"adminEmail": {
  "value": "sowthri@sowthriindustrialai.onmicrosoft.com"
}
```

### Behavior — deploy.yml updates

Add two new actions to the existing `workflow_dispatch` switch:

```yaml
on:
  workflow_dispatch:
    inputs:
      action:
        description: 'Action'
        type: choice
        options: [provision, deploy, teardown, resume, pause]
        default: deploy
```

**resume action:** Resumes Fabric F2 capacity (sets state = Active).
```yaml
- name: Resume Fabric capacity
  if: github.event.inputs.action == 'resume'
  run: |
    az fabric capacity resume \
      --name fab-refinerydigitaltwin-dev \
      --resource-group rg-refinerydigitaltwin-dev
```

**pause action:** Pauses Fabric F2 capacity (sets state = Paused, stops billing).
```yaml
- name: Pause Fabric capacity
  if: github.event.inputs.action == 'pause'
  run: |
    az fabric capacity suspend \
      --name fab-refinerydigitaltwin-dev \
      --resource-group rg-refinerydigitaltwin-dev
```

(Note: Bicep can provision the capacity; Azure CLI manages its state.)

### Behavior — KQL queries

Author 3-5 queries in `docs/kql/`. The queries assume Eventstream lands snapshots in Eventhouse table `snapshots` with native columns `timestamp`, `cycle`, `solved`, `tag_count`, `errors`, `tags` (where `tags` is dynamic).

**`reboiler_duty_timeseries.kql`:**
```kql
snapshots
| where solved == true
| project timestamp, reboiler_duty = todouble(tags['ES-REBOILER_DUTY.EnergyFlow'])
| where isnotnull(reboiler_duty)
| order by timestamp asc
| render timechart 
```

**`condenser_duty_timeseries.kql`:**
```kql
snapshots
| where solved == true
| project timestamp, condenser_duty = todouble(tags['ES-CONDENSER_DUTY.EnergyFlow'])
| where isnotnull(condenser_duty)
| order by timestamp asc
| render timechart
```

**`tag_extraction_pattern.kql`:** Reference query for extracting any tag, with the exact dynamic-field syntax.

**`solve_health.kql`:** Cycle solve duration over time, error rate, tag-count consistency check (should be 1550).

### Behavior — Manual Fabric portal setup

Some Fabric resources (workspace, Eventstream, Eventhouse) don't have full Bicep coverage. Operator does these in the portal once after Part A and capacity provisioning are done. Document the steps in `docs/runbooks/fabric_workspace_setup.md`.

**Steps:**
1. Sign in to https://app.fabric.microsoft.com with the work account
2. Workspaces → New workspace → name `refinery-digital-twin` → assign to F2 capacity (the one Bicep provisioned)
3. Inside workspace → New → Eventhouse → name `twin_eventhouse` → KQL database `twin_db`, table `snapshots` (auto-detected schema OK; can refine later)
4. Inside workspace → New → Eventstream → name `dwsim_stream` → Source: Azure Event Hub (cloud) — connection details from Bicep output (namespace, hub name, send rule connection string)
5. Eventstream → Destination: Eventhouse `twin_eventhouse` / `twin_db` / `snapshots` table
6. Eventstream → Activate / Publish
7. New → Real-Time Dashboard → name `twin_dashboard` → connect to `twin_db` → add tiles using KQL queries from `docs/kql/`

These steps can be partially scripted via Fabric REST API in a future hardening phase, but for A1 they're operator-driven.

## Outputs

| | |
|---|---|
| `2.automation/stage5/producer.py` | Stage 5 Event Hubs producer |
| `2.automation/stage5/position.json` | tail position (gitignored) |
| `infra/modules/eventhub.bicep` | Event Hubs Bicep module |
| `infra/modules/fabric_capacity.bicep` | Fabric F2 Bicep module |
| `infra/main.bicep` | extended to invoke new modules |
| `infra/main.parameters.json` | adds `adminEmail` |
| `.github/workflows/deploy.yml` | adds `resume` and `pause` actions |
| `docs/kql/*.kql` | KQL query library |
| `docs/runbooks/tenant_setup.md` | operator runbook (Part A) |
| `docs/runbooks/fabric_workspace_setup.md` | operator runbook (Fabric portal) |

## Acceptance criteria

**Part A — operator setup:**
- [ ] New Entra tenant created; tenant ID captured in runbook
- [ ] Admin user created with Global Admin role; UPN captured
- [ ] Power BI Pro purchased and assigned; receipt captured
- [ ] Fabric portal accessible with the work account
- [ ] Work account has Contributor role on existing Azure subscription
- [ ] `docs/runbooks/tenant_setup.md` committed on `phase-3-fabric`

**Part B — implementation:**
- [ ] `producer.py` exists at `2.automation/stage5/producer.py`
- [ ] Bicep modules `eventhub.bicep` + `fabric_capacity.bicep` exist
- [ ] `main.bicep` invokes both modules; `adminEmail` parameter wired
- [ ] `azd up --environment dev` provisions Event Hubs namespace + hub + Fabric F2 capacity (paused by default after creation)
- [ ] Fabric workspace created in portal, Eventstream connected to Event Hub, Eventhouse receives data
- [ ] `producer.py` running locally pushes 5+ snapshots to Event Hub, all visible in Eventhouse via `snapshots | take 10` KQL query
- [ ] At least one Real-Time Dashboard tile renders a chart from KQL query
- [ ] `deploy.yml` `resume` action wakes capacity in <60 s
- [ ] `deploy.yml` `pause` action pauses capacity, billing drops to $0

**End-to-end:**
- [ ] Stage 2 streamer running → Stage 5 producer running → snapshots arrive in Eventhouse within ~60 s of being written by Stage 2
- [ ] Run for 10 minutes, verify ~20 snapshots in Eventhouse, charts updating

## Anti-goals

- ✗ No twin ontology (F2 = phase-5)
- ✗ No agents (F3 = phase-6)
- ✗ No web UI (F5 = phase-7)
- ✗ No multi-substrate ingestion
- ✗ No setpoint write-back
- ✗ No production-grade dashboards (basic Fabric defaults only; F5 polishes)
- ✗ No modification of Phase 0a, Stage 1, Stage 2, or Phase 1 work
- ✗ No upgrade beyond F2 capacity
- ✗ No password automation, no credential storage in code
- ✗ No setup of additional users beyond the single admin

## Methodology rules

- Connection strings live in environment variables or Azure Key Vault, never in code or git
- Position file (`stage5/position.json`) is gitignored — runtime state, not source
- Atomic position writes (temp + rename) so crashes don't corrupt the offset
- Don't crash on a malformed JSONL line — log warning, skip, continue
- Don't crash on Event Hub transient failures — exponential backoff, persist if 3 consecutive fail
- Probe before assuming Fabric REST APIs (some are preview, behavior shifts)
- Sync solve, no threading
- Lane discipline: no edits to `1.AgenticAI/` or other lanes
- Conventional commits on `phase-3-fabric`

## Out of scope

- A2 (Stages 3 + 4 — REST API + OPC-UA)
- F2 / F3 / F5
- DWSIM-to-Azure VM migration (post-demo)
- Production hardening (managed identities, RBAC tightening, monitoring/alerting)

## Cost commitments

- **Recurring (always-on):** Power BI Pro $14/user/mo + Event Hubs Basic ~$11/mo = **~$25/mo**
- **On-demand (pay-as-you-go):** Fabric F2 ~$0.36/hr when active, $0 when paused. Demo runs ~$5-15/mo at typical usage
- **Total typical monthly:** $25-40/mo
- **Always-on equivalent (no pause):** ~$300/mo (avoid)

Operator commits to monthly recurring; pause-resume automation keeps Fabric variable cost low.

## Definition of done

1. Both runbooks committed and accurate
2. All Part A operator checks ticked
3. All Part B implementation criteria met
4. End-to-end smoke verified (snapshots flow Mac → Event Hub → Eventstream → Eventhouse → dashboard tile)
5. `phase-3-fabric` branch pushed
6. Operator approves; architect issues A2 briefing (REST + OPC-UA)

## Hand-off note for Claude Code

Part A (operator setup) runs in parallel with your Bicep + producer authoring. You can write Bicep, modules, producer code, KQL queries, deploy.yml updates, and runbook drafts (with placeholder values) in parallel. When the operator finishes Part A and gives you the work account UPN, slot it into `main.parameters.json` and run `azd up`.

For the producer:
- Stage 2's streamer is your reference for tail-reading patterns and JSONL semantics. Don't import — re-implement the tail logic. Producer's job is much simpler: tail current hour file, batch + send to Event Hub, advance position.
- Use `azure-eventhub` SDK (sync, not async — keep it simple)
- Connection string from `EVENT_HUB_CONNECTION_STRING` env var (operator sets this once after `azd up` from the Bicep output)

For Bicep:
- `Microsoft.Fabric/capacities` is the resource type for F-SKU capacity
- The `administration.members` array takes work-account email addresses
- Capacity provisioned via Bicep starts in `Active` state — immediately add a step (in deploy.yml or manual) to pause it after first provision so we don't burn $$

For deploy.yml:
- `azd up` provisions; an extra step pauses Fabric capacity
- New actions `resume` / `pause` use `az fabric capacity resume/suspend` CLI
- Test all 5 actions (provision, deploy, teardown, resume, pause) before claiming AC done

For KQL:
- Eventhouse table schema is auto-detected from incoming JSON. The `tags` field will be a dynamic; access via `tags['<tag-id>']` syntax
- Test queries in Fabric portal's KQL Queryset before adding to dashboard

Branch: `phase-3-fabric`. Conventional commits. Don't push without operator approval.

End of briefing.
