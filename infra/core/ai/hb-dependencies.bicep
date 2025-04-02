param location string = resourceGroup().location
param tags object = {}

@description('Name of the key vault')
param keyVaultName string
@description('Name of the storage account')
param storageAccountName string

@description('The AI Service resource location.')
param aiServiceLocation string

@description('The Search Service resource location.')
param searchServiceLocation string

@allowed([ 'Enabled', 'Disabled' ])
param publicNetworkAccess string = 'Enabled'

@description('The Search resource group id.')
param searchServiceResourceGroupId string

@description('The Azure Search service sku name.')
param searchServiceSkuName string

@description('The Search service semantic ranker level.')
param actualSearchServiceSemanticRankerLevel string

@description('Add a private endpoints for network connectivity')
param usePrivateEndpoint bool = false

@description('The storage output id')
param storageId string

@description('Names of the AI Services')
param aiServiceName string
// @description('Names of the AI Services')
// param aiServicesNames array = []
@description('Array of OpenAI model deployments')
param aiServiceModelDeployments array = []
@description('Name of the Log Analytics workspace')
param logAnalyticsName string = ''
@description('Name of the Application Insights instance')
param applicationInsightsName string = ''
@description('Name of the container registry')
param containerRegistryName string = ''
@description('Name of the Azure Cognitive Search service')
param searchServiceName string = ''

// @description('Embed Deployment Location')
// param embedDeploymentLocation string


module keyVault '../security/keyvault.bicep' = {
  name: 'keyvault'
  params: {
    location: location
    tags: tags
    name: keyVaultName
  }
}

module storageAccount '../storage/storage-account.bicep' = {
  name: 'storageAccount'
  params: {
    location: location
    tags: tags
    name: storageAccountName
    containers: [
      {
        name: 'default'
      }
    ]
    files: [
      {
        name: 'default'
      }
    ]
    queues: [
      {
        name: 'default'
      }
    ]
    tables: [
      {
        name: 'default'
      }
    ]
    corsRules: [
      {
        allowedOrigins: [
          'https://mlworkspace.azure.ai'
          'https://ml.azure.com'
          'https://*.ml.azure.com'
          'https://ai.azure.com'
          'https://*.ai.azure.com'
          'https://mlworkspacecanary.azure.ai'
          'https://mlworkspace.azureml-test.net'
        ]
        allowedMethods: [
          'GET'
          'HEAD'
          'POST'
          'PUT'
          'DELETE'
          'OPTIONS'
          'PATCH'
        ]
        maxAgeInSeconds: 1800
        exposedHeaders: [
          '*'
        ]
        allowedHeaders: [
          '*'
        ]
      }
    ]
    deleteRetentionPolicy: {
      allowPermanentDelete: false
      enabled: false
    }
    shareDeleteRetentionPolicy: {
      enabled: true
      days: 7
    }
  }
}

// module logAnalytics '../monitor/loganalytics.bicep' =
//   if (!empty(logAnalyticsName)) {
//     name: 'logAnalytics'
//     params: {
//       location: location
//       tags: tags
//       name: logAnalyticsName
//     }
//   }

// module applicationInsights '../monitor/applicationinsights.bicep' =
//   if (!empty(applicationInsightsName) && !empty(logAnalyticsName)) {
//     name: 'applicationInsights'
//     params: {
//       location: location
//       tags: tags
//       name: applicationInsightsName
//       logAnalyticsWorkspaceId: !empty(logAnalyticsName) ? logAnalytics.outputs.id : ''
//     }
//   }

// module containerRegistry '../host/container-registry.bicep' =
//   if (!empty(containerRegistryName)) {
//     name: 'containerRegistry'
//     params: {
//       location: location
//       tags: tags
//       name: containerRegistryName
//     }
//   }

module cognitiveServices '../ai/cognitiveservices.bicep' = 
  if (!empty(aiServiceName)) {
    name: 'cognitiveServices'
    params: {
      location: aiServiceLocation
      tags: tags
      name: aiServiceName
      kind: 'AIServices'
      deployments: aiServiceModelDeployments
    }
  }

// module searchService '../search/search-services.bicep' =
//   if (!empty(searchServiceName)) {
//     name: 'searchService'
//     params: {
//       location: location
//       tags: tags
//       name: searchServiceName
//       authOptions: { aadOrApiKey: { aadAuthFailureMode: 'http401WithBearerChallenge'}}
//     }
//   }

module searchService '../search/search-services.bicep' = 
  if (!empty(searchServiceName)) {
    name: 'search-service'
    //scope: resourceGroup(searchServiceResourceGroupId)
    params: {
      name: searchServiceName
      location: searchServiceLocation
      tags: tags
      disableLocalAuth: true
      sku: {
        name: searchServiceSkuName
      }
      semanticSearch: actualSearchServiceSemanticRankerLevel
      publicNetworkAccess: publicNetworkAccess == 'Enabled'
        ? 'enabled'
        : (publicNetworkAccess == 'Disabled' ? 'disabled' : null)
      sharedPrivateLinkStorageAccounts: usePrivateEndpoint ? [storageId] : []
    }
  }

// resource cognitiveServicesResources 'Microsoft.CognitiveServices/accounts@2023-05-01' = [for aiServiceName in aiServicesNames: {
//   name: aiServiceName
//   location: location
//   tags: tags
//   sku: {
//     name: 'S0'
//   }
//   kind: 'AIServices'
//   properties: {
//     customSubDomainName: aiServiceName
//   }
// }]  

output keyVaultId string = keyVault.outputs.id
output keyVaultName string = keyVault.outputs.name
output keyVaultEndpoint string = keyVault.outputs.endpoint

output storageAccountId string = storageAccount.outputs.id
output storageAccountName string = storageAccount.outputs.name

// output containerRegistryId string = !empty(containerRegistryName) ? containerRegistry.outputs.id : ''
// output containerRegistryName string = !empty(containerRegistryName) ? containerRegistry.outputs.name : ''
// output containerRegistryEndpoint string = !empty(containerRegistryName) ? containerRegistry.outputs.loginServer : ''

// output applicationInsightsId string = !empty(applicationInsightsName) ? applicationInsights.outputs.id : ''
// output applicationInsightsName string = !empty(applicationInsightsName) ? applicationInsights.outputs.name : ''
// output logAnalyticsWorkspaceId string = !empty(logAnalyticsName) ? logAnalytics.outputs.id : ''
// output logAnalyticsWorkspaceName string = !empty(logAnalyticsName) ? logAnalytics.outputs.name : ''

output aiServiceId string = cognitiveServices.outputs.id
output aiServiceName string = cognitiveServices.outputs.name
output aiServiceEndpoint string = cognitiveServices.outputs.endpoints['OpenAI Language Model Instance API']

// output aiEmbedServiceId string = cognitiveServicesEmbed.outputs.id
// output aiEmbedServicesName string = cognitiveServicesEmbed.outputs.name
// output aiEmbedServiceEndpoint string = cognitiveServicesEmbed.outputs.endpoints['OpenAI Language Model Instance API']


// si on fait multiple service
//output aiServicesNames array = aiServicesNames
//output cognitiveServicesResourceIds array = [for resource in aiServicesNames: resourceId('Microsoft.CognitiveServices/accounts@2023-05-01', resource.id)]


output searchServiceId string = !empty(searchServiceName) ? searchService.outputs.id : ''
output searchServiceName string = !empty(searchServiceName) ? searchService.outputs.name : ''
output searchServiceEndpoint string = !empty(searchServiceName) ? searchService.outputs.endpoint : ''

output searchServicePrincipalId string = searchService.outputs.principalId
