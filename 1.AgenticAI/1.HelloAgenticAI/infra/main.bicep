// HelloAgenticAI — root deployment. Subscription-scoped: creates the resource
// group, then composes the eleven service modules into it.
//
// Phase 1 services: identity, observability, keyvault, cosmos, storage,
// openai, contentsafety, registry, container-env, container-app.
// Search is module-conditional (deploySearch=false in v1).
// APIM and Redis are framework hooks deferred to refinery verticals — no
// modules in v1.

targetScope = 'subscription'

// ----- parameters -----

@minLength(1)
@maxLength(20)
@description('Environment name (dev, staging, prod). Used in the resource group name and tags.')
param environmentName string

@minLength(1)
@description('Azure region. Default swedencentral per docs/ARCHITECTURE.md.')
param location string

@description('Conditional: deploy AI Search. Off by default in v1; refinery verticals enable it.')
param deploySearch bool = false

@minValue(1)
@maxValue(2000)
@description('Capacity for the gpt-4o deployment (in 1K TPM units).')
param openAiChatLargeCapacity int = 10

@minValue(1)
@maxValue(2000)
@description('Capacity for the gpt-4o-mini deployment (in 1K TPM units).')
param openAiChatMiniCapacity int = 30

@minValue(1)
@maxValue(2000)
@description('Capacity for the text-embedding-3-large deployment (in 1K TPM units).')
param openAiEmbeddingsCapacity int = 30

@minLength(1)
@description('Container image for the agent. Sourced from SERVICE_AGENT_IMAGE_NAME (an azd output populated after every `azd deploy`) via main.parameters.json substitution; falls back to the quickstart placeholder pre-first-deploy. Plumbing this through Bicep avoids the trap where a hardcoded default in the container-app module silently reverts the image to the placeholder on any solo `azd provision`.')
param containerImage string

// ----- derived -----

var tags = {
  project: 'helloagenticai'
  environment: environmentName
  managedBy: 'bicep'
}

// ----- resource group -----

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-helloagenticai-${environmentName}'
  location: location
  tags: tags
}

// Deterministic short suffix for globally-unique names (ACR, KV, storage, AOAI)
var resourceToken = uniqueString(rg.id)
var resourceTokenAlnum = replace(resourceToken, '-', '')

// ----- modules -----

module identity 'modules/identity.bicep' = {
  scope: rg
  name: 'identity'
  params: {
    name: 'id-helloagenticai-${environmentName}-${resourceToken}'
    location: location
    tags: tags
  }
}

module observability 'modules/observability.bicep' = {
  scope: rg
  name: 'observability'
  params: {
    logName: 'log-helloagenticai-${environmentName}-${resourceToken}'
    appiName: 'appi-helloagenticai-${environmentName}-${resourceToken}'
    location: location
    tags: tags
  }
}

module keyvault 'modules/keyvault.bicep' = {
  scope: rg
  name: 'keyvault'
  params: {
    // KV names: 3-24, alphanumeric + hyphens, must start with letter, globally unique
    name: 'kv-${take(resourceTokenAlnum, 21)}'
    location: location
    tags: tags
    principalId: identity.outputs.principalId
  }
}

module cosmos 'modules/cosmos.bicep' = {
  scope: rg
  name: 'cosmos'
  params: {
    name: 'cosmos-helloai-${environmentName}-${resourceToken}'
    location: location
    tags: tags
    principalId: identity.outputs.principalId
  }
}

module storage 'modules/storage.bicep' = {
  scope: rg
  name: 'storage'
  params: {
    // Storage names: 3-24 lowercase alphanumeric, no hyphens, globally unique
    name: take('sthelloai${environmentName}${resourceTokenAlnum}', 24)
    location: location
    tags: tags
    principalId: identity.outputs.principalId
  }
}

module search 'modules/search.bicep' = if (deploySearch) {
  scope: rg
  name: 'search'
  params: {
    name: 'srch-helloai-${environmentName}-${resourceToken}'
    location: location
    tags: tags
  }
}

module openai 'modules/openai.bicep' = {
  scope: rg
  name: 'openai'
  params: {
    name: 'aoai-helloai-${environmentName}-${resourceToken}'
    location: location
    tags: tags
    principalId: identity.outputs.principalId
    chatLargeCapacity: openAiChatLargeCapacity
    chatMiniCapacity: openAiChatMiniCapacity
    embeddingsCapacity: openAiEmbeddingsCapacity
  }
}

module contentsafety 'modules/contentsafety.bicep' = {
  scope: rg
  name: 'contentsafety'
  params: {
    name: 'cs-helloai-${environmentName}-${resourceToken}'
    location: location
    tags: tags
    principalId: identity.outputs.principalId
  }
}

module registry 'modules/registry.bicep' = {
  scope: rg
  name: 'registry'
  params: {
    // ACR names: 5-50 lowercase alphanumeric, no hyphens, globally unique
    name: take('crhelloai${environmentName}${resourceTokenAlnum}', 50)
    location: location
    tags: tags
    principalId: identity.outputs.principalId
  }
}

module containerEnv 'modules/container-env.bicep' = {
  scope: rg
  name: 'container-env'
  params: {
    name: 'cae-helloagenticai-${environmentName}-${resourceToken}'
    location: location
    tags: tags
    logAnalyticsWorkspaceName: observability.outputs.logAnalyticsName
  }
}

module containerApp 'modules/container-app.bicep' = {
  scope: rg
  name: 'container-app'
  params: {
    name: 'ca-agent-${environmentName}-${resourceToken}'
    location: location
    tags: tags
    environmentId: containerEnv.outputs.id
    identityResourceId: identity.outputs.id
    identityClientId: identity.outputs.clientId
    registryServer: registry.outputs.loginServer
    openAiEndpoint: openai.outputs.endpoint
    cosmosEndpoint: cosmos.outputs.endpoint
    contentSafetyEndpoint: contentsafety.outputs.endpoint
    keyVaultEndpoint: keyvault.outputs.uri
    appInsightsConnectionString: observability.outputs.appInsightsConnectionString
    image: containerImage
  }
}

// Phase 4 deliverable 5 — App Insights workbook for the operational
// dashboard demo link. Workbook JSON is hand-authored in
// `infra/workbooks/agent-observability.workbook.json` and loaded at
// template-compile time. Cost-trend chart deferred to framework-v2 per
// the kickoff 30-min threshold; see the workbook JSON's placeholder
// section + framework-v2-backlog.md.
module workbook 'modules/workbook.bicep' = {
  scope: rg
  name: 'workbook-agent-observability'
  params: {
    displayName: 'HelloAgenticAI Agent Observability'
    appInsightsResourceId: observability.outputs.appInsightsId
    workbookJsonContent: loadTextContent('workbooks/agent-observability.workbook.json')
    location: location
    tags: tags
  }
}

// ----- outputs (consumed by `azd env get-values`) -----

output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_LOCATION string = location

output AZURE_OPENAI_ENDPOINT string = openai.outputs.endpoint
output AZURE_OPENAI_NAME string = openai.outputs.name
output AZURE_OPENAI_CHAT_LARGE_DEPLOYMENT string = openai.outputs.chatLargeDeployment
output AZURE_OPENAI_CHAT_MINI_DEPLOYMENT string = openai.outputs.chatMiniDeployment
output AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT string = openai.outputs.embeddingsDeployment

output AZURE_COSMOS_ENDPOINT string = cosmos.outputs.endpoint
output AZURE_COSMOS_NAME string = cosmos.outputs.name
output AZURE_COSMOS_DATABASE string = cosmos.outputs.databaseName

output AZURE_KEY_VAULT_ENDPOINT string = keyvault.outputs.uri
output AZURE_KEY_VAULT_NAME string = keyvault.outputs.name

output AZURE_APPLICATIONINSIGHTS_CONNECTION_STRING string = observability.outputs.appInsightsConnectionString
output AZURE_LOG_ANALYTICS_WORKSPACE_NAME string = observability.outputs.logAnalyticsName
output AZURE_APPLICATION_INSIGHTS_ID string = observability.outputs.appInsightsId

output AZURE_CONTENT_SAFETY_ENDPOINT string = contentsafety.outputs.endpoint
output AZURE_CONTENT_SAFETY_NAME string = contentsafety.outputs.name

// Phase 4 batch 7 — Workbook resource id. README's "operational dashboard"
// link is constructed as
// https://portal.azure.com/#@/resource/{workbookId}
output AZURE_WORKBOOK_ID string = workbook.outputs.id
output AZURE_WORKBOOK_NAME string = workbook.outputs.name

output AZURE_STORAGE_BLOB_ENDPOINT string = storage.outputs.blobEndpoint
output AZURE_STORAGE_NAME string = storage.outputs.name

output AZURE_CONTAINER_REGISTRY_ENDPOINT string = registry.outputs.loginServer
output AZURE_CONTAINER_REGISTRY_NAME string = registry.outputs.name

output AZURE_CONTAINER_APP_NAME string = containerApp.outputs.name
output AZURE_CONTAINER_APP_FQDN string = containerApp.outputs.fqdn
output AZURE_CONTAINER_APP_ENDPOINT string = 'https://${containerApp.outputs.fqdn}'

output AZURE_MANAGED_IDENTITY_CLIENT_ID string = identity.outputs.clientId
output AZURE_MANAGED_IDENTITY_NAME string = identity.outputs.name
