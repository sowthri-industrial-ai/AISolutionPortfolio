// Azure AI Search service. STUBBED in v1 — main.bicep deploys this only when
// deploySearch=true (default false). Refinery verticals enable this for
// vector + hybrid retrieval over technical docs / P&IDs / MOC.

@description('Search service name.')
param name string

@description('Azure region.')
param location string

@description('Resource tags.')
param tags object = {}

@allowed([ 'free', 'basic', 'standard' ])
@description('SKU. basic is the cheapest paid tier with full features.')
param sku string = 'basic'

resource search 'Microsoft.Search/searchServices@2023-11-01' = {
  name: name
  location: location
  tags: tags
  sku: { name: sku }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'default'
    publicNetworkAccess: 'enabled'
    semanticSearch: 'free'
    authOptions: {
      aadOrApiKey: {
        aadAuthFailureMode: 'http401WithBearerChallenge'
      }
    }
    disableLocalAuth: false
  }
  identity: { type: 'SystemAssigned' }
}

output id string = search.id
output name string = search.name
output endpoint string = 'https://${search.name}.search.windows.net'
