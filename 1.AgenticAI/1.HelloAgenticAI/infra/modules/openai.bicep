// Azure OpenAI account with three model deployments:
//   gpt-4o (planner)              — GlobalStandard
//   gpt-4o-mini (router/reflector) — GlobalStandard
//   text-embedding-3-large (RAG)   — Standard
// AAD-only (disableLocalAuth: true). Identity granted "Cognitive Services
// OpenAI User" on the account. Deployments are serialized via dependsOn to
// avoid AOAI rate-limiting on parallel create.

@description('AOAI account name. Must be globally unique; becomes the customSubDomain.')
param name string

@description('Azure region.')
param location string

@description('Resource tags.')
param tags object = {}

@description('Principal granted Cognitive Services OpenAI User on the account.')
param principalId string

@minValue(1)
@maxValue(2000)
@description('Capacity for gpt-4o (1K TPM units).')
param chatLargeCapacity int = 10

@minValue(1)
@maxValue(2000)
@description('Capacity for gpt-4o-mini (1K TPM units).')
param chatMiniCapacity int = 30

@minValue(1)
@maxValue(2000)
@description('Capacity for text-embedding-3-large (1K TPM units).')
param embeddingsCapacity int = 30

resource aoai 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: name
  location: location
  tags: tags
  kind: 'OpenAI'
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

resource gpt4o 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: aoai
  name: 'gpt-4o'
  sku: { name: 'GlobalStandard', capacity: chatLargeCapacity }
  properties: {
    model: { format: 'OpenAI', name: 'gpt-4o', version: '2024-08-06' }
    versionUpgradeOption: 'OnceCurrentVersionExpired'
    raiPolicyName: 'Microsoft.DefaultV2'
  }
}

resource gpt4omini 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: aoai
  name: 'gpt-4o-mini'
  dependsOn: [ gpt4o ]
  sku: { name: 'GlobalStandard', capacity: chatMiniCapacity }
  properties: {
    model: { format: 'OpenAI', name: 'gpt-4o-mini', version: '2024-07-18' }
    versionUpgradeOption: 'OnceCurrentVersionExpired'
    raiPolicyName: 'Microsoft.DefaultV2'
  }
}

resource embed 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: aoai
  name: 'text-embedding-3-large'
  dependsOn: [ gpt4omini ]
  sku: { name: 'Standard', capacity: embeddingsCapacity }
  properties: {
    model: { format: 'OpenAI', name: 'text-embedding-3-large', version: '1' }
    versionUpgradeOption: 'OnceCurrentVersionExpired'
    raiPolicyName: 'Microsoft.DefaultV2'
  }
}

// Cognitive Services OpenAI User — Azure built-in role, public id
var openaiUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd' // gitleaks:allow

resource roleAssign 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: aoai
  name: guid(aoai.id, principalId, openaiUserRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', openaiUserRoleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

output id string = aoai.id
output name string = aoai.name
output endpoint string = aoai.properties.endpoint
output chatLargeDeployment string = gpt4o.name
output chatMiniDeployment string = gpt4omini.name
output embeddingsDeployment string = embed.name
