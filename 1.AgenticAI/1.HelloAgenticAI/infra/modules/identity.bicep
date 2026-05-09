// User-assigned managed identity used by the Container App for AAD-auth to
// every Azure dependency (AOAI, Cosmos, Key Vault, Storage, ACR, App Insights).
// One identity, attached to one Container App, granted least-privilege roles
// at each dependency's scope.

@description('Resource name.')
param name string

@description('Azure region.')
param location string

@description('Resource tags.')
param tags object = {}

resource mi 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: name
  location: location
  tags: tags
}

output id string = mi.id
output name string = mi.name
output principalId string = mi.properties.principalId
output clientId string = mi.properties.clientId
