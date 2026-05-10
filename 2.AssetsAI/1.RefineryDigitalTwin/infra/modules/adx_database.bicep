// KQL database `twin_db` for Stage 5 snapshot ingestion. Schema bootstrapped
// at deploy time via a Kusto admin script:
//   .create-merge table snapshots (...)             ← idempotent, no-ops on match
//   .create-or-alter table snapshots ingestion json mapping 'snapshots_mapping' '[...]'
//
// The data connection (adx_data_connection.bicep) references both the table
// and the mapping by name. Dev SKU has 50 GB cache; aggressive defaults below
// keep us comfortably inside that.
//
// Schema mirrors Stage 2's snapshot shape exactly (committed in Stage 2 at
// 7c2fe03 — timestamp/cycle/solved/solve_time_s/cycle_duration_s/tag_count/
// errors[]/tags{}). `tags` and `errors` are dynamic so KQL queries access
// them via bracket syntax (see docs/kql/tag_extraction_pattern.kql).

@description('Parent ADX cluster name (database is RG-scoped via parent).')
param clusterName string

@description('Database name.')
param databaseName string = 'twin_db'

@description('Azure region (must match cluster location).')
param location string

@description('Soft-delete (cold storage) retention. ISO-8601 duration. Default 7 days for Dev SKU.')
param softDeletePeriod string = 'P7D'

@description('Hot cache retention. ISO-8601 duration. Stays in fast-query cache. Default 1 day.')
param hotCachePeriod string = 'P1D'

resource cluster 'Microsoft.Kusto/clusters@2023-08-15' existing = {
  name: clusterName
}

resource db 'Microsoft.Kusto/clusters/databases@2023-08-15' = {
  parent: cluster
  name: databaseName
  location: location
  kind: 'ReadWrite'
  properties: {
    softDeletePeriod: softDeletePeriod
    hotCachePeriod: hotCachePeriod
  }
}

// Bootstrap the snapshots table + JSON ingestion mapping. Both commands are
// idempotent so re-deploys via `azd up` succeed without manual cleanup:
//   .create-merge table     — creates if missing; no-op if columns match
//   .create-or-alter mapping — replaces mapping definition
resource initSchema 'Microsoft.Kusto/clusters/databases/scripts@2023-08-15' = {
  parent: db
  name: 'init-snapshots-schema'
  properties: {
    scriptContent: '''
.create-merge table snapshots (timestamp:datetime, cycle:long, solved:bool, solve_time_s:real, cycle_duration_s:real, tag_count:long, errors:dynamic, tags:dynamic)

.create-or-alter table snapshots ingestion json mapping 'snapshots_mapping' '[{"column":"timestamp","path":"$.timestamp"},{"column":"cycle","path":"$.cycle"},{"column":"solved","path":"$.solved"},{"column":"solve_time_s","path":"$.solve_time_s"},{"column":"cycle_duration_s","path":"$.cycle_duration_s"},{"column":"tag_count","path":"$.tag_count"},{"column":"errors","path":"$.errors"},{"column":"tags","path":"$.tags"}]'
'''
    continueOnErrors: false
  }
}

output databaseName string = db.name
output databaseId string = db.id
