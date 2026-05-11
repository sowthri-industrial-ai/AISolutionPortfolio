// Azure Data Explorer (Kusto) cluster — single Dev SKU instance with system-
// assigned managed identity used by the Event Hub data connection to ingest
// from the Stage 5 producer's hub (see adx_data_connection.bicep).
//
// Pause/resume via `az kusto cluster start/stop`:
//   - Stopped → $0 compute billing (storage still bills, but Dev SKU is small).
//   - System MI + role assignments persist across stop/start.
//   - Resume time ~1-2 min; ingestion picks up from consumer-group checkpoint.
//
// F1B pivot: replaces fabric_capacity.bicep. ADX is the standalone Azure
// service that backs KQL queries on the existing personal subscription —
// no new tenant required (vs Microsoft Fabric, which needs a Workforce
// tenant + Power BI Pro license).

@description('Cluster name. Lowercase letters and digits only, NO hyphens; 4-22 chars; globally unique.')
param name string

@description('Azure region.')
param location string

@description('Resource tags. azd-service-name added inside the module.')
param tags object = {}

@description('Cluster SKU. Dev(No SLA)_Standard_D11_v2 is the universally-available dev tier (~$0.34/hr running).')
param skuName string = 'Dev(No SLA)_Standard_D11_v2'

@description('Cluster SKU tier. Basic for Dev SKUs, Standard for prod.')
@allowed([
  'Basic'
  'Standard'
])
param skuTier string = 'Basic'

@description('Cluster capacity (instance count). Dev SKUs are single-instance.')
@minValue(1)
@maxValue(2)
param capacity int = 1

resource cluster 'Microsoft.Kusto/clusters@2023-08-15' = {
  name: name
  location: location
  tags: union(tags, { 'azd-service-name': 'adx' })
  sku: {
    name: skuName
    tier: skuTier
    capacity: capacity
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    enableStreamingIngest: true
    enableDoubleEncryption: false
    publicNetworkAccess: 'Enabled'
  }
}

output clusterId string = cluster.id
output clusterName string = cluster.name
output clusterUri string = cluster.properties.uri
output dataIngestionUri string = cluster.properties.dataIngestionUri
output principalId string = cluster.identity.principalId