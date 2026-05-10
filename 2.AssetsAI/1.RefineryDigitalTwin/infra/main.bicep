// Refinery Digital Twin — root deployment. Subscription-scoped: creates the
// resource group, then deploys the placeholder Static Web App and the Event
// Hubs namespace + hub for the Stage 5 producer.
//
// Phase 1 foundation:    Static Web App.
// Phase 3 (A1 Wave 1):   Event Hubs Basic + producer-send rule (this file).
// Phase 3 (A1 Wave 2):   Fabric F2 capacity. The fabric_capacity.bicep
//                        module file exists alongside this one but is NOT
//                        invoked yet — Wave 2 wires it in (one-line module
//                        block + adminEmail param from Part A tenant setup).

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

// Briefing-spec output names (item 4): RESOURCE_GROUP_NAME + DEMO_URL.
// AZURE_RESOURCE_GROUP is the azd convention; both are exported.
output RESOURCE_GROUP_NAME string = rg.name
