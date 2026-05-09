// Azure Container Registry (Basic SKU). Stores the agent image.
// admin user disabled — Container App pulls via the user-assigned managed
// identity granted "AcrPull" on the registry.

@description('Registry name (5-50 chars, lowercase alphanumeric, globally unique).')
param name string

@description('Azure region.')
param location string

@description('Resource tags.')
param tags object = {}

@description('Principal granted AcrPull on the registry.')
param principalId string

@allowed([ 'Basic', 'Standard', 'Premium' ])
param sku string = 'Basic'

resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: name
  location: location
  tags: tags
  sku: { name: sku }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
    zoneRedundancy: 'Disabled'
    anonymousPullEnabled: false
  }
}

// AcrPull — Azure built-in role, public id
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d' // gitleaks:allow

resource roleAssign 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, principalId, acrPullRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

output id string = acr.id
output name string = acr.name
output loginServer string = acr.properties.loginServer
