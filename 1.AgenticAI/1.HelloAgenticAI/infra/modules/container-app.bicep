// Phase 1 placeholder Container App. Initial image is the Microsoft k8se
// quickstart (port 80, won't match our 8000 target) — `azd deploy` then
// builds the local Dockerfile, pushes to ACR, and updates the app to use
// the placeholder.py image which DOES listen on 8000.
//
// Tag `azd-service-name=agent` is how azd matches azure.yaml's `agent`
// service to this Container App during deploy.

@description('Resource name.')
param name string

@description('Azure region.')
param location string

@description('Resource tags. The module adds azd-service-name=agent.')
param tags object = {}

@description('Container Apps Environment resource id.')
param environmentId string

@description('User-assigned managed identity resource id.')
param identityResourceId string

@description('Managed identity client id (for AZURE_CLIENT_ID env var → DefaultAzureCredential).')
param identityClientId string

@description('ACR login server (e.g. "<name>.azurecr.io"). The pull credential is the managed identity.')
param registryServer string

@description('Initial image. azd deploy replaces this with the locally-built placeholder image.')
param image string = 'mcr.microsoft.com/k8se/quickstart:latest'

@minValue(1)
@maxValue(65535)
@description('Container target port. Matches placeholder.py / future Chainlit port.')
param targetPort int = 8000

@minValue(0)
@maxValue(25)
param minReplicas int = 0

@minValue(1)
@maxValue(25)
param maxReplicas int = 1

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: name
  location: location
  tags: union(tags, { 'azd-service-name': 'agent' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identityResourceId}': {}
    }
  }
  properties: {
    managedEnvironmentId: environmentId
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: targetPort
        transport: 'auto'
        allowInsecure: false
        traffic: [
          { weight: 100, latestRevision: true }
        ]
      }
      registries: [
        {
          server: registryServer
          identity: identityResourceId
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'agent'
          image: image
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            { name: 'AZURE_CLIENT_ID', value: identityClientId }
            { name: 'CONTAINER_APP_NAME', value: name }
          ]
          probes: [
            {
              type: 'Liveness'
              httpGet: { path: '/health', port: targetPort }
              initialDelaySeconds: 10
              periodSeconds: 30
              failureThreshold: 3
            }
            {
              type: 'Readiness'
              httpGet: { path: '/health', port: targetPort }
              initialDelaySeconds: 5
              periodSeconds: 10
              failureThreshold: 3
            }
          ]
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
      }
    }
  }
}

output id string = app.id
output name string = app.name
output fqdn string = app.properties.configuration.ingress.fqdn
