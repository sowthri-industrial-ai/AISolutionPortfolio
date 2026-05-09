// Container Apps Environment configured to ship container stdout/stderr to
// the Log Analytics workspace from observability.bicep. Single Consumption
// workload profile; no zone redundancy in dev.

@description('Resource name.')
param name string

@description('Azure region.')
param location string

@description('Resource tags.')
param tags object = {}

@description('Name of the Log Analytics workspace (in the same RG) used for container logs.')
param logAnalyticsWorkspaceName string

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: logAnalyticsWorkspaceName
}

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
    zoneRedundant: false
  }
}

output id string = env.id
output name string = env.name
output defaultDomain string = env.properties.defaultDomain
