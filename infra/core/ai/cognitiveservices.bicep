metadata description = 'Creates an Azure Cognitive Services instance.'

param tags object = {}

param disableLocalAuth bool = false
param deployments array = []
//param serviceAccounts array = []
param name string
param location string
@description('The custom subdomain name used to access the API. Defaults to the value of the name parameter.')
param customSubDomainName string = name

param kind string = 'OpenAI'

@allowed([ 'Enabled', 'Disabled' ])
param publicNetworkAccess string = 'Enabled'
param sku object = {
  name: 'S0'
}
param bypass string = 'AzureServices'
param allowedIpRules array = []
param networkAcls object = empty(allowedIpRules) ? {
  defaultAction: 'Allow'
  bypass: bypass
} : {
  ipRules: allowedIpRules
  defaultAction: 'Deny'
}

// TODO si on fait multiple accounts (per diff location aiServicesLocation)
//var uniqueLocations = [for i in range(0, length(deployments)): (i == 0 || deployments[i].location != deployments[i - 1].location) ? deployments[i].location : null]
// resource accounts 'Microsoft.CognitiveServices/accounts@2023-05-01' = [for location in uniqueLocations: if(location != null) {
//   name: deployments[indexOf(deployments, location)].accountName //'account-${location}' // Unique name for each account
//   location: location
//   tags: tags
//   kind: kind
//   properties: {
//     customSubDomainName: 'account-${location}'
//     publicNetworkAccess: publicNetworkAccess
//     networkAcls: networkAcls
//     disableLocalAuth: disableLocalAuth
//   }
//   sku: sku
// } ]


// Pour le starter, finalement on va deployer seulememt un service type account ( si on a besoi de d'autre region , on fera via le portail...)
resource account 'Microsoft.CognitiveServices/accounts@2023-05-01' =  {
  name: name
  location: location
  tags: tags
  kind: kind
  properties: {
    customSubDomainName: customSubDomainName
    publicNetworkAccess: publicNetworkAccess
    networkAcls: networkAcls
    disableLocalAuth: disableLocalAuth
  }
  sku: sku
}


@batchSize(1)
resource deployment 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = [for deployment in deployments: {
  parent: account
  name: deployment.name
  properties: {
    model: deployment.model
  }
  sku: deployment.sku ?? null
  // {
  //   name: 'Standard'
  //   capacity: 20
  // }
}]

output endpoint string = account.properties.endpoint
output endpoints object = account.properties.endpoints
output id string = account.id
output name string = account.name

// TODO si on fait multiple accounts (per diff location aiServicesLocation)
// output endpoints array = [for i in range(0, length(uniqueLocations)): accounts[i].properties.endpoint]
// output endpointsObject array = [for i in range(0, length(uniqueLocations)): {
//   endpoint: accounts[i].properties.endpoint
//   endpoints: accounts[i].properties.endpoints
// }]
// output ids array = [for i in range(0, length(uniqueLocations)): accounts[i].id]
// output names array = [for i in range(0, length(uniqueLocations)): accounts[i].name]



