// Event Hubs namespace + hub + producer-send authorization rule for the
// Stage 5 producer. Basic SKU is sufficient for ~120 events/hour at 30 s
// solve cadence (1 partition handles up to 1 MB/s ingress).
//
// The producer-send rule is hub-scoped, not namespace-scoped, so the
// resulting connection string includes `EntityPath=<eventHubName>` and
// EventHubProducerClient.from_connection_string auto-detects the hub.
//
// Connection string is intentionally NOT a Bicep output (avoids storing
// in deployment history). Operator fetches via:
//   az eventhubs eventhub authorization-rule keys list \
//     --resource-group rg-refinerydigitaltwin-${env} \
//     --namespace-name <eventHubNamespaceName> \
//     --eventhub-name <eventHubName> \
//     --name producer-send \
//     --query primaryConnectionString -o tsv

@description('Event Hubs namespace name. Globally unique, 6-50 chars.')
param namespaceName string

@description('Event Hub instance name (within namespace).')
param eventHubName string

@description('Azure region.')
param location string

@description('Resource tags.')
param tags object = {}

resource ehns 'Microsoft.EventHub/namespaces@2024-01-01' = {
  name: namespaceName
  location: location
  tags: tags
  sku: {
    name: 'Basic'
    tier: 'Basic'
    capacity: 1
  }
  properties: {
    isAutoInflateEnabled: false
    publicNetworkAccess: 'Enabled'
  }
}

resource eh 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = {
  parent: ehns
  name: eventHubName
  properties: {
    messageRetentionInDays: 1
    partitionCount: 1
  }
}

resource sendRule 'Microsoft.EventHub/namespaces/eventhubs/authorizationRules@2024-01-01' = {
  parent: eh
  name: 'producer-send'
  properties: {
    rights: ['Send']
  }
}

output eventHubNamespaceName string = ehns.name
output eventHubName string = eh.name
output sendRuleId string = sendRule.id
output sendRuleName string = sendRule.name
