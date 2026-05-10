# ADX Dashboard Setup — manual portal steps

Manual steps to wire a basic Real-Time-style dashboard in the Azure Data
Explorer web UI on top of the `snapshots` table. Bicep provisions the
cluster + database + data connection automatically; the dashboard tiles
are clicked together once in the portal because ADX dashboards aren't
fully scriptable yet.

Run this **once** after the first successful end-to-end smoke test
(`azd up` + producer sending events + `snapshots | take 10` returning
rows).

---

## Prerequisites

- `azd up --environment dev` ran cleanly; output values include:
  - `AZURE_KUSTO_CLUSTER_NAME` (e.g., `adxrtdev<token>`)
  - `AZURE_KUSTO_CLUSTER_URI` (e.g., `https://<name>.<region>.kusto.windows.net`)
  - `AZURE_KUSTO_DATABASE` (`twin_db`)
- ADX cluster is **Running**. If it's `Stopped`, run the `resume` workflow
  action or `az kusto cluster start -g rg-refinerydigitaltwin-dev -n <name>`.
- Stage 5 producer has sent at least 10 events recently
  (`snapshots | count` returns ≥ 10).
- Operator's signed-in Azure account has `AllDatabasesAdmin` or `Database
  user` permission on `twin_db` (deploy-time Bicep grants this implicitly
  to the principal running `azd up`; for additional users, add via the
  ADX permissions blade).

## 1. Open the ADX web UI

Either:

- From the Azure portal: navigate to the ADX cluster resource → top of
  the overview page, click **Query** to open the Kusto Web Explorer
  (KWE) directly on this cluster.
- Or open https://dataexplorer.azure.com directly and add the cluster
  by URI (paste `AZURE_KUSTO_CLUSTER_URI`).

The left sidebar should show the cluster → `twin_db` → `Tables` →
`snapshots`.

## 2. Verify ingestion before building tiles

In the query pane, run:

```kql
snapshots | count
```

Expected: a single row with `Count >= 10` (or however many events the
producer has sent). If `0`:

- Confirm Stage 2 streamer + Stage 5 producer are running on the Mac
  and the producer's log shows `cumulative=N` advancing.
- Confirm the data connection is healthy: ADX cluster → **Data
  connections** blade → `dwsim-stream` → check **State** is `Running`.
- Confirm the consumer group `adx-twin` exists on the Event Hub:
  `az eventhubs eventhub consumer-group list -g rg-refinerydigitaltwin-dev
  --namespace-name <evhns> --eventhub-name dwsim-snapshots -o table`
- Wait 1-2 minutes — first ingestion has a small startup lag.

Then sanity-check a few rows:

```kql
snapshots
| order by timestamp desc
| take 5
| project timestamp, cycle, solved, tag_count, errors_count = array_length(errors)
```

## 3. Save the four canonical queries to the database

In the KWE, top-right menu → **Save as Query**. Paste each of the
queries from `docs/kql/` and save with the filename's stem as the name:

| Query name in KWE | Source file |
|---|---|
| `condenser_duty_timeseries` | `docs/kql/condenser_duty_timeseries.kql` |
| `reboiler_duty_timeseries` | `docs/kql/reboiler_duty_timeseries.kql` |
| `tag_extraction_pattern` | `docs/kql/tag_extraction_pattern.kql` |
| `solve_health` | `docs/kql/solve_health.kql` |

These are now reusable across queries and dashboards on this cluster.

## 4. Create the dashboard

In the KWE left sidebar → **Dashboards** → **New dashboard** →
`twin_dashboard`. The wizard prompts for a data source — select the
ADX cluster + `twin_db` database.

Add tiles one per query:

| Tile name | Query | Visualization |
|---|---|---|
| Condenser duty | paste `condenser_duty_timeseries.kql` body | Time chart (auto from `render timechart`) |
| Reboiler duty | paste `reboiler_duty_timeseries.kql` body | Time chart |
| Solve health (pipeline summary) | paste `solve_health.kql` body | Stat / table (single-row summary) |
| Tag explorer | paste `tag_extraction_pattern.kql` body | Table |

For each: click **+ Add tile** → paste KQL → click **Run** to verify it
returns data → click **Apply changes** → drag/resize on the dashboard
canvas.

The Tag explorer tile lets viewers change `target_tag` via the query
editor at the top — useful for ad-hoc exploration during demos.

Save the dashboard.

## 5. Pause / resume operations

The deploy.yml workflow_dispatch has two new actions for cost control:

- **pause**: `az kusto cluster stop` → cluster goes to `Stopped`,
  compute billing drops to $0. Storage still bills, but Dev SKU
  storage is small (single-digit dollars/month).
- **resume**: `az kusto cluster start` → cluster goes to `Running`
  in ~1-2 min, ingestion resumes from the consumer group's last
  checkpoint.

Or run locally:

```bash
RG=rg-refinerydigitaltwin-dev
CLUSTER=$(az kusto cluster list -g "$RG" --query "[0].name" -o tsv)
az kusto cluster stop  -g "$RG" -n "$CLUSTER"   # pause
az kusto cluster start -g "$RG" -n "$CLUSTER"   # resume
```

### ⚠️ Event Hub retention gotcha — D5 from the design review

**Event Hubs Basic SKU has 1-day message retention.** If ADX is stopped
for **>24 hours**, queued events drop from the hub before ADX can
ingest them. Demo implications:

- For demos with multi-day gaps, **resume ADX before starting the
  producer**. The producer should be stopped or paused alongside ADX
  if you want zero data loss.
- If ADX has been stopped >24h, the first batch of events after
  resume will only contain what's been written to the hub since the
  retention window started — anything older was dropped.
- Cleanest demo pattern: pause both `producer.py` (Ctrl-C on the Mac)
  and ADX cluster simultaneously; resume both in the same session.
- Hardening for production: upgrade Event Hubs to Standard SKU
  (variable retention up to 7 days, ~$22/mo) — out of scope for the
  demo.

## 6. Sharing the dashboard

In the KWE dashboard view → **Share** → add Entra ID users by UPN with
**Viewer** or **Editor** permission. They'll need at minimum **Database
user** role on `twin_db` to render the queries.

For the portfolio site / public demo: the ADX dashboard URL is
shareable but requires the viewer to be signed in to Azure with
appropriate permissions. The public-facing path is:

1. Operator clicks **Resume** in deploy.yml workflow dispatch (wakes
   ADX in ~1-2 min)
2. Operator starts Stage 2 + Stage 5 on the Mac (events flow)
3. Reviewer hits the Static Web App at `DEMO_URL` (still serves the
   placeholder until F5 lands)
4. For now, dashboard screenshots in `docs/screenshots/` (TBD) tell
   the story
