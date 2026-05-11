// Event Hub data connection: ingest from `dwsim-snapshots` hub into `snapshots`
// table on the `twin_db` database. Authenticates via the cluster's system-
// assigned managed identity:
//
//   1. Consumer group `$Default` on the existing hub. Event Hub Basic SKU
//      doesn't allow custom consumer groups — only $Default. The Standard
//      SKU upgrade ($22/mo) would unlock dedicated groups; out of scope.
//   2. Role assignment: cluster's principalId → built-in
//      "Azure Event Hubs Data Receiver" role, scoped to the specific hub
//      (least privilege; not the whole namespace).
//   3. Data connection itself, kind=EventHub, dataFormat=MULTIJSON,
//      mappingRuleName=snapshots_mapping (created by adx_database.bicep's
//      init-snapshots-schema script).
//
// Deploying this module requires the deploying principal (operator's azd
// login) to have permission to assign roles — Owner OR User Access
// Administrator on the RG / subscription.
//
// On `az kusto cluster stop`: ingestion pauses. Event Hub Basic SKU has
// 1-day retention, so if ADX stays stopped >24 h, queued events drop from
// the hub. On resume, ingestion picks up from the consumer group's last
// checkpoint (no replay of old events).

@description('Parent ADX cluster name (RG-scoped).')
param clusterName string

@description('ADX database name.')
param databaseName string

@description('Event Hub namespace name (existing — provisioned by eventhub.bicep).')
param eventHubNamespaceName string

@description('Event Hub instance name (existing).')
param eventHubName string

@description('ADX cluster system-assigned principalId (output of adx_cluster.bicep).')
param clusterPrincipalId string

@description('Azure region (cluster + hub location).')
param location string

@description('Data connection name.')
param dataConnectionName string = 'dwsim-stream'

// Existing Event Hub references — module sources truth from eventhub.bicep
// without modifying it.
resource ehNs 'Microsoft.EventHub/namespaces@2024-01-01' existing = {
  name: eventHubNamespaceName
}

resource eh 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' existing = {
  parent: ehNs
  name: eventHubName
}

// Built-in role: Azure Event Hubs Data Receiver
//   role definition ID: a638d3c7-ab3a-418d-83e6-5f17a39d4fde
var ehDataReceiverRoleId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  'a638d3c7-ab3a-418d-83e6-5f17a39d4fde'
)

resource roleAssign 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: eh
  // Deterministic GUID — re-deploys are idempotent.
  name: guid(eh.id, clusterPrincipalId, ehDataReceiverRoleId)
  properties: {
    principalId: clusterPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: ehDataReceiverRoleId
  }
}

resource cluster 'Microsoft.Kusto/clusters@2023-08-15' existing = {
  name: clusterName
}

resource db 'Microsoft.Kusto/clusters/databases@2023-08-15' existing = {
  parent: cluster
  name: databaseName
}

// The data connection itself. dataFormat=MULTIJSON: tolerant of single or
// multiple JSON objects per Event Hub message body. Stage 5 producer sends
// one JSON object per message, but MULTIJSON is the safer general-purpose
// format.
resource dataConnection 'Microsoft.Kusto/clusters/databases/dataConnections@2023-08-15' = {
  parent: db
  name: dataConnectionName
  location: location
  kind: 'EventHub'
  properties: {
    eventHubResourceId: eh.id
    // Using $Default because Event Hub is Basic SKU (no custom consumer
    // groups allowed). If we ever add other consumers, upgrade EH to
    // Standard ($22/mo total) and create a dedicated group then.
    consumerGroup: '$Default'
    tableName: 'snapshots'
    mappingRuleName: 'snapshots_mapping'
    dataFormat: 'MULTIJSON'
    compression: 'None'
    managedIdentityResourceId: cluster.id
  }
  dependsOn: [
    roleAssign
  ]
}

output dataConnectionName string = dataConnection.name
output consumerGroupName string = '$Default'
