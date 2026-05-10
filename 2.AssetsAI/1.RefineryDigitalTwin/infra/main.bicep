// Refinery Digital Twin — root deployment. Subscription-scoped: creates the
// resource group, then deploys a placeholder Static Web App into it.
//
// Phase 1 foundation: only a Static Web App. Stages 2-6 + Features 1, 2, 3, 5
// add Eventhouse, Eventstream, Fabric IQ, Foundry, AI Search, etc. — all
// modular additions on top of this skeleton.

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

// ----- outputs (consumed by `azd env get-values`) -----

output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_LOCATION string = location

output STATIC_WEB_APP_NAME string = staticWebApp.outputs.name
output DEMO_URL string = 'https://${staticWebApp.outputs.defaultHostname}'

// Briefing-spec output names (item 4): RESOURCE_GROUP_NAME + DEMO_URL.
// AZURE_RESOURCE_GROUP is the azd convention; both are exported.
output RESOURCE_GROUP_NAME string = rg.name
