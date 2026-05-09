// Azure AI Content Safety. Used for input + output guardrails (Phase 2+).
// AAD-only. Identity granted "Cognitive Services User" on the account.

@description('Resource name. Becomes the customSubDomain.')
param name string

@description('Azure region.')
param location string

@description('Resource tags.')
param tags object = {}

@description('Principal granted Cognitive Services User on the account.')
param principalId string

resource cs 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: name
  location: location
  tags: tags
  kind: 'ContentSafety'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    customSubDomainName: name
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow'
      bypass: 'AzureServices'
    }
    disableLocalAuth: true
  }
}

// Cognitive Services User — Azure built-in role, public id
var csUserRoleId = 'a97b65f3-24c7-4388-baec-2e87135dc908' // gitleaks:allow

resource roleAssign 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: cs
  name: guid(cs.id, principalId, csUserRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', csUserRoleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

output id string = cs.id
output name string = cs.name
output endpoint string = cs.properties.endpoint
