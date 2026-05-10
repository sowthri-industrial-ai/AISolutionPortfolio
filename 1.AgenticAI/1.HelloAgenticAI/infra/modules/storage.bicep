// Storage account (Standard_LRS) with one blob container `eval-artefacts` for
// run transcripts and evaluation outputs. AAD-only (allowSharedKeyAccess: false).
// Used by Phase 4+ eval harness; in Phase 1 it just exists.

@description('Storage account name (3-24 chars, lowercase alphanumeric only, globally unique).')
param name string

@description('Azure region.')
param location string

@description('Resource tags.')
param tags object = {}

@description('Principal granted Storage Blob Data Contributor on the account.')
param principalId string

resource sa 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: name
  location: location
  tags: tags
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    minimumTlsVersion: 'TLS1_2'
    allowSharedKeyAccess: false
    allowBlobPublicAccess: false
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Allow'
    }
    encryption: {
      services: {
        blob: { enabled: true }
        file: { enabled: true }
      }
      keySource: 'Microsoft.Storage'
    }
    supportsHttpsTrafficOnly: true
  }
}

resource blob 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: sa
  name: 'default'
  properties: {
    deleteRetentionPolicy: { enabled: true, days: 7 }
  }
}

resource artefacts 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blob
  name: 'eval-artefacts'
  properties: {
    publicAccess: 'None'
  }
}

// Storage Blob Data Contributor — Azure built-in role, public id.
// Verified via `az role definition list --name "Storage Blob Data Contributor"`
// — always re-verify role IDs from the CLI before commit, never hand-type.
var blobDataContribRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe' // gitleaks:allow

resource roleAssign 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: sa
  name: guid(sa.id, principalId, blobDataContribRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobDataContribRoleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

output id string = sa.id
output name string = sa.name
output blobEndpoint string = sa.properties.primaryEndpoints.blob
