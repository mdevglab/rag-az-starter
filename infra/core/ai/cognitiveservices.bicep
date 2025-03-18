metadata description = 'Creates an Azure Cognitive Services instance.'

param tags object = {}

param disableLocalAuth bool = false
param deployments array = []
param serviceAccounts array = []

param kind string = 'OpenAI'
//param kind string = 'AIServices'

@allowed([ 'Enabled', 'Disabled' ])
param publicNetworkAccess string = 'Enabled'
param sku object = {
  name: 'S0'
}

param allowedIpRules array = []
param networkAcls object = empty(allowedIpRules) ? {
  defaultAction: 'Allow'
} : {
  ipRules: allowedIpRules
  defaultAction: 'Deny'
}


var uniqueLocations = [for i in range(0, length(deployments)): (i == 0 || deployments[i].location != deployments[i - 1].location) ? deployments[i].location : null]

resource accounts 'Microsoft.CognitiveServices/accounts@2023-05-01' = [for location in uniqueLocations: if(location != null) {
  name: deployments[location].accountName //'account-${location}' // Unique name for each account
  location: location
  tags: tags
  kind: kind
  properties: {
    customSubDomainName: 'account-${location}'
    publicNetworkAccess: publicNetworkAccess
    networkAcls: networkAcls
    disableLocalAuth: disableLocalAuth
  }
  sku: {
    name: deployments[location].sku.name
    capacity: deployments[location].sku.capacity
  }
} ]


// resource account 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
//   name: name
//   location: location
//   tags: tags
//   kind: kind
//   properties: {
//     customSubDomainName: customSubDomainName
//     publicNetworkAccess: publicNetworkAccess
//     networkAcls: networkAcls
//     disableLocalAuth: disableLocalAuth
//   }
//   sku: sku
// }

@batchSize(1)
resource deployment 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = [for deployment in deployments: {
  parent: accounts[indexOf(uniqueLocations, deployment.location)] // Find the parent account by location
  name: deployment.name
  properties: {
    model: deployment.model
    raiPolicyName: contains(deployment, 'raiPolicyName') ? deployment.raiPolicyName : null
  }
  sku: contains(deployment, 'sku') ? deployment.sku : {
    name: 'Standard'
    capacity: 20
  }
}]

// output endpoint string = account.properties.endpoint
// output endpoints object = account.properties.endpoints
// output id string = account.id
// output name string = account.name


output endpoints array = [for i in range(0, length(uniqueLocations)): accounts[i].properties.endpoint]

output endpointsObject array = [for i in range(0, length(uniqueLocations)): {
  endpoint: accounts[i].properties.endpoint
  endpoints: accounts[i].properties.endpoints
}]

output ids array = [for i in range(0, length(uniqueLocations)): accounts[i].id]

output names array = [for i in range(0, length(uniqueLocations)): accounts[i].name]
