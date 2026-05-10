// Microsoft Fabric F2 capacity. Provisioned in Wave 2; this module is
// present in Wave 1 but NOT invoked from main.bicep.
//
// Wave 2 wiring (one-line add to main.bicep):
//   module fabricCapacity 'modules/fabric_capacity.bicep' = {
//     scope: rg
//     name: 'fabric-capacity'
//     params: {
//       name: 'fab-refinerydigitaltwin-${environmentName}'
//       location: location
//       tags: tags
//       adminEmail: adminEmail   // from main.parameters.json, set in Wave 2
//     }
//   }
//
// adminEmail must be the work-account UPN created in Part A of the A1
// briefing (e.g., sowthri@<tenant>.onmicrosoft.com). Personal Microsoft
// accounts are rejected by Fabric.
//
// Capacity provisioned via Bicep starts in Active state and bills at
// ~$0.36/hr. Pause it post-provision via the deploy.yml `pause` action
// (or `az fabric capacity suspend`) before walking away.

@description('Fabric capacity name. Lowercase alphanumeric + hyphens, 3-63 chars.')
param name string

@description('Azure region.')
param location string

@description('Resource tags. The azd-service-name tag is added inside this module.')
param tags object = {}

@description('Email of the work-account capacity admin (UPN from Part A tenant setup).')
param adminEmail string

resource capacity 'Microsoft.Fabric/capacities@2023-11-01' = {
  name: name
  location: location
  tags: union(tags, { 'azd-service-name': 'fabric' })
  sku: {
    name: 'F2'
    tier: 'Fabric'
  }
  properties: {
    administration: {
      members: [adminEmail]
    }
  }
}

output capacityId string = capacity.id
output capacityName string = capacity.name
