// Cosmos DB (NoSQL, serverless). Database `agent` with two containers:
//   sessions  — conversation/session state (TTL 30d)
//   traces    — agent step traces (TTL 30d)
// AAD-only (disableLocalAuth: true). Data plane access via Cosmos DB built-in
// "Data Contributor" role granted to the Container App's managed identity.

@description('Cosmos DB account name (3-44 chars, lowercase alphanumeric + hyphens, globally unique).')
param name string

@description('Azure region.')
param location string

@description('Resource tags.')
param tags object = {}

@description('Principal granted Cosmos DB built-in Data Contributor.')
param principalId string

@description('Logical database name.')
param databaseName string = 'agent'

@minValue(60)
@maxValue(2592000)
@description('Container TTL in seconds (default 30 days).')
param containerTtl int = 2592000

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-08-15' = {
  name: name
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    capabilities: [
      { name: 'EnableServerless' }
    ]
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: true
    minimalTlsVersion: 'Tls12'
    networkAclBypass: 'AzureServices'
  }
}

resource db 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-08-15' = {
  parent: cosmos
  name: databaseName
  properties: {
    resource: { id: databaseName }
  }
}

resource sessions 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-08-15' = {
  parent: db
  name: 'sessions'
  properties: {
    resource: {
      id: 'sessions'
      partitionKey: { paths: [ '/sessionId' ], kind: 'Hash' }
      defaultTtl: containerTtl
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
      }
    }
  }
}

resource traces 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-08-15' = {
  parent: db
  name: 'traces'
  properties: {
    resource: {
      id: 'traces'
      partitionKey: { paths: [ '/sessionId' ], kind: 'Hash' }
      defaultTtl: containerTtl
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
      }
    }
  }
}

// Cosmos data plane: built-in role "Cosmos DB Built-in Data Contributor"
var dataContribRoleDefId = '00000000-0000-0000-0000-000000000002'

resource sqlRoleAssign 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-08-15' = {
  parent: cosmos
  name: guid(cosmos.id, principalId, dataContribRoleDefId)
  properties: {
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/${dataContribRoleDefId}'
    principalId: principalId
    scope: cosmos.id
  }
}

output id string = cosmos.id
output name string = cosmos.name
output endpoint string = cosmos.properties.documentEndpoint
output databaseName string = db.name
