// Log Analytics workspace + workspace-based Application Insights.
// Container Apps Environment ingests container stdout/stderr into the workspace.
// AgentEventEmitter (Phase 2+) publishes structured events to App Insights.

@description('Log Analytics workspace name.')
param logName string

@description('App Insights component name.')
param appiName string

@description('Azure region.')
param location string

@description('Resource tags.')
param tags object = {}

@minValue(7)
@maxValue(730)
@description('Retention days for Log Analytics. Dev default 30.')
param retentionInDays int = 30

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logName
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: retentionInDays
    features: {
      enableLogAccessUsingOnlyResourcePermissions: true
    }
  }
}

resource appi 'Microsoft.Insights/components@2020-02-02' = {
  name: appiName
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logs.id
    IngestionMode: 'LogAnalytics'
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

output logAnalyticsId string = logs.id
output logAnalyticsName string = logs.name
output appInsightsId string = appi.id
output appInsightsName string = appi.name
output appInsightsConnectionString string = appi.properties.ConnectionString
