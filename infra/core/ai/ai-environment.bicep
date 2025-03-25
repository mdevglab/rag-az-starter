

@description('The AI Hub resource name.')
param hubName string
@description('The AI Project resource name.')
param projectName string
@description('The Key Vault resource name.')
param keyVaultName string
@description('The Storage Account resource name.')
param storageAccountName string

@minLength(1)
@description('The AI Service resource location.')
param aiServiceLocation string

@minLength(1)
@description('The Search Service resource location.')
param searchServiceLocation string

@description('The AI Service resource name.')
param aiServiceName string
@description('The AI Services connection name.')
param aiServicesConnectionName string
// @description('The AI Services resource names.')
// param aiServicesNames array = []
// @description('The AI Services connection name.')
// param aiServicesConnectionNames array = []
@description('The AI Services model deployments.')
param aiServiceModelDeployments array = []
@description('The AI Services content safety connection name.')
param aiServicesContentSafetyConnectionName string

@description('The Log Analytics resource name.')
param logAnalyticsName string = ''
@description('The Application Insights resource name.')
param applicationInsightsName string = ''
@description('The Application Insights resource id.')
param applicationInsightsId string 

@description('The Container Registry resource name.')
param containerRegistryName string = ''

@description('The Azure Search resource name.')
param searchServiceName string

@description('The Search resource group id.')
param searchServiceResourceGroupId string

@description('The Azure Search service sku name.')
param searchServiceSkuName string

@description('The Search service semantic ranker level.')
param actualSearchServiceSemanticRankerLevel string

@allowed([ 'Enabled', 'Disabled' ])
param publicNetworkAccess string = 'Enabled'

@description('Add a private endpoints for network connectivity')
param usePrivateEndpoint bool = false

@description('The storage output id')
param storageId string

@description('The Azure Search connection name.')
param searchConnectionName string = ''
param tags object = {}

module hubDependencies './hb-dependencies.bicep' = {
  name: 'hubDependencies'
  params: {
    aiServiceLocation: aiServiceLocation
    searchServiceLocation: searchServiceLocation
    tags: tags
    keyVaultName: keyVaultName
    storageAccountName: storageAccountName
    containerRegistryName: containerRegistryName
    applicationInsightsName: applicationInsightsName
    logAnalyticsName: logAnalyticsName
    //aiServicesNames: aiServicesNames
    aiServiceName: aiServiceName
    aiServiceModelDeployments: aiServiceModelDeployments
    searchServiceName: searchServiceName
    publicNetworkAccess: publicNetworkAccess
    searchServiceResourceGroupId : searchServiceResourceGroupId
    searchServiceSkuName: searchServiceSkuName
    actualSearchServiceSemanticRankerLevel: actualSearchServiceSemanticRankerLevel
    usePrivateEndpoint: usePrivateEndpoint
    storageId: storageId
  }
}

module hub './hub.bicep' = {
  name: 'hub'
  params: {
    location: aiServiceLocation
    tags: tags
    name: hubName
    displayName: hubName
    keyVaultId: hubDependencies.outputs.keyVaultId
    storageAccountId: hubDependencies.outputs.storageAccountId
    containerRegistryId: hubDependencies.outputs.containerRegistryId
    applicationInsightsId: applicationInsightsId //hubDependencies.outputs.applicationInsightsId
    aiServiceName: hubDependencies.outputs.aiServiceName
    aiServicesConnectionName: aiServicesConnectionName
    //aiServicesNames: hubDependencies.outputs.aiServicesNames
    //aiServicesConnectionNames: aiServicesConnectionNames
    aiServicesContentSafetyConnectionName: aiServicesContentSafetyConnectionName
    aiSearchName: hubDependencies.outputs.searchServiceName
    aiSearchConnectionName: searchConnectionName
  }
}

module project './project.bicep' = {
  name: 'project'
  params: {
    location: aiServiceLocation
    tags: tags
    name: projectName
    displayName: projectName
    hubName: hub.outputs.name
  }
}


// Outputs
// Resource Group
output resourceGroupName string = resourceGroup().name

// Hub
output hubName string = hub.outputs.name
output hubPrincipalId string = hub.outputs.principalId

// Project
output projectName string = project.outputs.name
output projectPrincipalId string = project.outputs.principalId

// Key Vault
output keyVaultName string = hubDependencies.outputs.keyVaultName
output keyVaultEndpoint string = hubDependencies.outputs.keyVaultEndpoint

// Application Insights
// output applicationInsightsName string = hubDependencies.outputs.applicationInsightsName
// output logAnalyticsWorkspaceName string = hubDependencies.outputs.logAnalyticsWorkspaceName

// Container Registry
output containerRegistryName string = hubDependencies.outputs.containerRegistryName
output containerRegistryEndpoint string = hubDependencies.outputs.containerRegistryEndpoint

// Storage Account
output storageAccountName string = hubDependencies.outputs.storageAccountName

// AI Services
output aiServiceName string = hubDependencies.outputs.aiServiceName
output aiServiceEndpoint string = hubDependencies.outputs.aiServiceEndpoint
output aiServiceId string = hubDependencies.outputs.aiServiceId

// output aiServicesNames array = hubDependencies.outputs.aiServicesNames
// output aiServicesConnectionNames array = hub.outputs.aiServicesConnectionNames
// output cognitiveServicesResourceIds array = hubDependencies.outputs.cognitiveServicesResourceIds
// output aiServicesConnectionIds array = hub.outputs.aiServicesConnectionIds

// Search
output searchServiceName string = hubDependencies.outputs.searchServiceName
output searchServiceEndpoint string = hubDependencies.outputs.searchServiceEndpoint
output searchServicePrincipalId string = hubDependencies.outputs.searchServicePrincipalId
output searchServiceId string = hubDependencies.outputs.searchServiceId

//Discoveryurl
output discoveryUrl string = project.outputs.discoveryUrl
