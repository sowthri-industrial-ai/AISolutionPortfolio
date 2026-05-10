// Static Web App for the Phase 1 placeholder landing page. Free SKU is
// sufficient; full Feature 5 may upgrade to Standard if custom domains or
// authentication are needed.
//
// Free SKU region constraint: westus2 / centralus / eastus2 / westeurope /
// eastasia only — see main.bicep for parameter defaulting.
//
// Content is deployed via `azd deploy` (azd resolves to `swa deploy`),
// not via SWA's GitHub repository connection. repositoryUrl/branch are
// intentionally empty.

@description('Resource name.')
param name string

@description('Azure region (must be Free SKU-supported).')
param location string

@description('Resource tags.')
param tags object = {}

resource swa 'Microsoft.Web/staticSites@2024-04-01' = {
  name: name
  location: location
  tags: union(tags, { 'azd-service-name': 'web' })
  sku: {
    name: 'Free'
    tier: 'Free'
  }
  properties: {
    repositoryUrl: ''
    branch: ''
    buildProperties: {}
  }
}

output id string = swa.id
output name string = swa.name
output defaultHostname string = swa.properties.defaultHostname
