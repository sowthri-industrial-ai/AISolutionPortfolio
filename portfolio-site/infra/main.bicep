// Portfolio site — root deployment. Subscription-scoped: creates the resource
// group, then composes the Static Web App module into it.
//
// This stack is deliberately separate from
// `1.AgenticAI/1.HelloAgenticAI/infra/main.bicep` so the portfolio's deploy
// cadence (publish on every PR merge) is decoupled from the agent runtime's
// cadence (provisions cost-bearing AOAI / Cosmos / Container Apps). Sharing
// observability is fine and free — the Phase 1 Log Analytics workspace can be
// passed in via `logAnalyticsWorkspaceId` so SWA diagnostic events land in the
// same workspace; leave the param empty to skip wiring entirely.
//
// Per ADR-0002: portfolio = Astro + Tailwind on Azure Static Web Apps (Free).

targetScope = 'subscription'

// ----- parameters -----

@minLength(1)
@maxLength(20)
@description('Environment name (dev, staging, prod). Used in the resource group name and tags.')
param environmentName string

@minLength(1)
@description('Azure region. Default swedencentral per HelloAgenticAI Phase 1 convention. SWA is a global service but the resource record needs a region anchor.')
param location string

@description('Optional: existing Log Analytics workspace resource ID for SWA diagnostic settings. Leave empty to skip diagnostic settings (no error). Set via `azd env set AZURE_PORTFOLIO_LAW_ID <full-resource-id>` to wire SWA logs into the Phase 1 LAW for single-pane observability — ingestion is well under the LAW free-tier ceiling for a static site.')
param logAnalyticsWorkspaceId string = ''

// ----- derived -----

var tags = {
  project: 'helloagenticai'
  environment: environmentName
  managedBy: 'bicep'
  component: 'portfolio'
}

// ----- resource group -----

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-helloagenticai-portfolio-${environmentName}'
  location: location
  tags: tags
}

// Deterministic short suffix for globally-unique names (SWA is global)
var resourceToken = uniqueString(rg.id)

// ----- modules -----

module swa 'modules/swa.bicep' = {
  scope: rg
  name: 'swa-portfolio'
  params: {
    // SWA names: 1-60 chars, alphanumeric + hyphens, must start with letter.
    // 'stapp-helloai-portfolio-${env}-${token}' = up to 41 chars in dev — well under the 60 ceiling.
    name: 'stapp-helloai-portfolio-${environmentName}-${resourceToken}'
    location: location
    tags: tags
    logAnalyticsWorkspaceId: logAnalyticsWorkspaceId
  }
}

// ----- outputs (consumed by `azd env get-values` + Batch 6 README/smoke-test) -----

output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_LOCATION string = location

output AZURE_PORTFOLIO_SWA_NAME string = swa.outputs.name
output AZURE_PORTFOLIO_DEFAULT_HOSTNAME string = swa.outputs.defaultHostname
output AZURE_PORTFOLIO_URL string = 'https://${swa.outputs.defaultHostname}'
