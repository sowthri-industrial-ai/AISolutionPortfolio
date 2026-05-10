// Key Vault for non-Azure secrets (Langfuse Cloud public/secret keys per
// ADR-0001). RBAC mode (no access policies). Soft-delete on; purge protection
// off in dev so teardown is clean. Production verticals should set
// enablePurgeProtection: true.

@description('Resource name (3-24 chars, alphanumeric + hyphens, must start with letter).')
param name string

@description('Azure region.')
param location string

@description('Resource tags.')
param tags object = {}

@description('Principal (managed identity) granted Key Vault Secrets User on the vault.')
param principalId string

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    sku: { family: 'A', name: 'standard' }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    enablePurgeProtection: null
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow'
      bypass: 'AzureServices'
    }
  }
}

// Key Vault Secrets User — Azure built-in role, public id
var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6' // gitleaks:allow

resource roleAssign 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: kv
  name: guid(kv.id, principalId, keyVaultSecretsUserRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

output id string = kv.id
output name string = kv.name
output uri string = kv.properties.vaultUri
