// Refinery Digital Twin — root deployment. Subscription-scoped: creates the
// resource group, then deploys the placeholder Static Web App, Event Hubs
// (for Stage 5 producer), and Azure Data Explorer (cluster + database +
// data connection) for KQL ingestion.
//
// Phase 1 foundation:    Static Web App.
// Phase 3 (A1 Wave 1):   Event Hubs Basic + producer-send rule.
// Phase 3 (F1B pivot):   Azure Data Explorer Dev SKU cluster, twin_db
//                        database with snapshots table, and EventHub data
//                        connection authenticated via the cluster's system-
//                        assigned managed identity (Azure Event Hubs Data
//                        Receiver role on the hub). Replaces the original
//                        Microsoft Fabric plan — ADX runs on the existing
//                        personal subscription and needs no new tenant.

targetScope = 'subscription'

// ----- parameters -----

@minLength(1)
@maxLength(20)
@description('Environment name (dev, staging, prod). Used in the resource group name and tags.')
param environmentName string

@minLength(1)
@description('Azure region for the resource group. Default swedencentral per portfolio convention (mirrors HelloAgenticAI).')
param location string

@minLength(1)
@description('Azure region for the Static Web App. Free SKU only supports westus2 / centralus / eastus2 / westeurope / eastasia. Default westeurope is the closest Free-tier region to swedencentral.')
param staticWebAppLocation string = 'westeurope'

// ----- derived -----

var tags = {
  project: 'refinerydigitaltwin'
  environment: environmentName
  managedBy: 'bicep'
}

// ----- resource group -----

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-refinerydigitaltwin-${environmentName}'
  location: location
  tags: tags
}

// Deterministic short suffix for globally-unique names
var resourceToken = uniqueString(rg.id)

// ----- modules -----

module staticWebApp 'modules/staticwebapp.bicep' = {
  scope: rg
  name: 'staticwebapp'
  params: {
    name: 'swa-refinerydigitaltwin-${environmentName}-${resourceToken}'
    location: staticWebAppLocation
    tags: tags
  }
}

// Event Hubs namespace + hub + producer-send authorization rule. Stage 5
// producer reads the hub-scoped connection string (which includes EntityPath)
// from `EVENT_HUB_CONNECTION_STRING` env var; operator fetches via
// `az eventhubs eventhub authorization-rule keys list` post-deploy.
module eventHub 'modules/eventhub.bicep' = {
  scope: rg
  name: 'eventhub'
  params: {
    namespaceName: 'evhns-refinerydigitaltwin-${environmentName}-${resourceToken}'
    eventHubName: 'dwsim-snapshots'
    location: location
    tags: tags
  }
}

// Azure Data Explorer cluster (Dev SKU, system-assigned MI). Pause/resume
// via deploy.yml's resume/pause actions to control compute billing.
// Cluster name: lowercase letters/digits only, no hyphens, 4-22 chars.
// `adxrdt${env}${take(token, 8)}` is 17-21 chars — fits the limit.
module adxCluster 'modules/adx_cluster.bicep' = {
  scope: rg
  name: 'adx-cluster'
  params: {
    name: 'adxrdt${environmentName}${take(resourceToken, 8)}'
    location: location
    tags: tags
  }
}

// twin_db database — schema bootstrapped at deploy time via embedded KQL
// admin script (snapshots table + JSON ingestion mapping).
module adxDatabase 'modules/adx_database.bicep' = {
  scope: rg
  name: 'adx-database'
  params: {
    clusterName: adxCluster.outputs.clusterName
    databaseName: 'twin_db'
    location: location
  }
}

// Event Hub data connection — system-MI auth + $Default consumer group
// (Event Hub Basic SKU doesn't allow custom consumer groups; Standard
// upgrade would unlock that) + role assignment (Azure Event Hubs Data
// Receiver scoped to the specific hub). On `az kusto cluster stop`,
// ingestion pauses; on resume, picks up from consumer-group checkpoint.
// Event Hub Basic SKU has 1-day retention — ADX stopped >24 h drops
// queued events.
module adxDataConnection 'modules/adx_data_connection.bicep' = {
  scope: rg
  name: 'adx-data-connection'
  params: {
    clusterName: adxCluster.outputs.clusterName
    databaseName: adxDatabase.outputs.databaseName
    eventHubNamespaceName: eventHub.outputs.eventHubNamespaceName
    eventHubName: eventHub.outputs.eventHubName
    clusterPrincipalId: adxCluster.outputs.principalId
    location: location
  }
}

// ----- outputs (consumed by `azd env get-values`) -----

output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_LOCATION string = location

output STATIC_WEB_APP_NAME string = staticWebApp.outputs.name
output DEMO_URL string = 'https://${staticWebApp.outputs.defaultHostname}'

// Event Hubs outputs — consumed by the operator to assemble the connection
// string for the Stage 5 producer's EVENT_HUB_CONNECTION_STRING env var.
output EVENT_HUB_NAMESPACE string = eventHub.outputs.eventHubNamespaceName
output EVENT_HUB_NAME string = eventHub.outputs.eventHubName
output EVENT_HUB_SEND_RULE_NAME string = eventHub.outputs.sendRuleName

// ADX outputs — consumed by KQL queries (cluster URI + database name) and
// by deploy.yml resume/pause via runtime `az kusto cluster list` discovery
// (cluster name).
output AZURE_KUSTO_CLUSTER_NAME string = adxCluster.outputs.clusterName
output AZURE_KUSTO_CLUSTER_URI string = adxCluster.outputs.clusterUri
output AZURE_KUSTO_DATABASE string = adxDatabase.outputs.databaseName
output AZURE_KUSTO_INGESTION_URI string = adxCluster.outputs.dataIngestionUri

// Briefing-spec output names (item 4): RESOURCE_GROUP_NAME + DEMO_URL.
// AZURE_RESOURCE_GROUP is the azd convention; both are exported.
output RESOURCE_GROUP_NAME string = rg.name
