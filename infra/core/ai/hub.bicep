@description('The AI Foundry Hub Resource name')
param name string
@description('The display name of the AI Foundry Hub Resource')
param displayName string = name
@description('The storage account ID to use for the AI Foundry Hub Resource')
param storageAccountId string
@description('The key vault ID to use for the AI Foundry Hub Resource')
param keyVaultId string
@description('The application insights ID to use for the AI Foundry Hub Resource')
param applicationInsightsId string = ''
@description('The container registry ID to use for the AI Foundry Hub Resource')
param containerRegistryId string = ''

@description('The Azure Cognitive Search service name to use for the AI Foundry Hub Resource')
param aiSearchName string = ''
@description('The Azure Cognitive Search service connection name to use for the AI Foundry Hub Resource')
param aiSearchConnectionName string


@description('The SKU name to use for the AI Foundry Hub Resource')
param skuName string = 'Basic'
@description('The SKU tier to use for the AI Foundry Hub Resource')
@allowed(['Basic', 'Free', 'Premium', 'Standard'])
param skuTier string = 'Basic'
@description('The public network access setting to use for the AI Foundry Hub Resource')
@allowed(['Enabled','Disabled'])
param publicNetworkAccess string = 'Enabled'


@description('The AI Service account name to use for the AI Foundry Hub Resource')
param aiServiceName string
@description('The AI Services connection name to use for the AI Foundry Hub Resource')
param aiServicesConnectionName string
// @description('The AI Services account name to use for the AI Foundry Hub Resource')
// param aiServicesNames array = []
// @description('The AI Services connection name to use for the AI Foundry Hub Resource')
// param aiServicesConnectionNames array = []
@description('The AI Services Content Safety connection name to use for the AI Foundry Hub Resource')
param aiServicesContentSafetyConnectionName string


param location string
param tags object = {}

resource hub 'Microsoft.MachineLearningServices/workspaces@2024-07-01-preview' = {
  name: name
  location: location
  tags: tags
  sku: {
    name: skuName
    tier: skuTier
  }
  kind: 'Hub'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    friendlyName: displayName
    storageAccount: storageAccountId
    keyVault: keyVaultId
    applicationInsights: !empty(applicationInsightsId) ? applicationInsightsId : null
    containerRegistry: !empty(containerRegistryId) ? containerRegistryId : null
    hbiWorkspace: false
    managedNetwork: {
      isolationMode: 'Disabled'
    }
    v1LegacyMode: false
    publicNetworkAccess: publicNetworkAccess
  }

  // TODO if multiple AI services
  // resource aiServiceConnections 'connections' =  [for aiServiceName in aiServicesNames: {
  //   name: '${aiServiceName}-connection'
  //   //location: location
  //   properties: {
  //     category: 'AIServices'
  //     authType: 'ApiKey'
  //     isSharedToAll: true
  //     target: reference(resourceId('Microsoft.CognitiveServices/accounts', aiServiceName)).properties.endpoint
  //     metadata: {
  //       ApiVersion: '2023-07-01-preview'
  //       ApiType: 'azure'
  //       ResourceId: resourceId('Microsoft.CognitiveServices/accounts', aiServiceName)
  //     }
  //     credentials: {
  //       key: listKeys(resourceId('Microsoft.CognitiveServices/accounts', aiServiceName), '2023-05-01').key1
  //     }
  //   }
  // }]

  resource aiServiceConnection 'connections' = {
    name: aiServicesConnectionName
    properties: {
      category: 'AIServices'
      authType: 'ApiKey'
      isSharedToAll: true
      target: aiService.properties.endpoint
      metadata: {
        ApiVersion: '2023-07-01-preview'
        ApiType: 'azure'
        ResourceId: aiService.id
      }
      credentials: {
        key: aiService.listKeys().key1
      }
    }
  }

  resource contentSafetyConnection 'connections' = {
    name: aiServicesContentSafetyConnectionName
    properties: {
      category: 'AzureOpenAI'
      authType: 'ApiKey'
      isSharedToAll: true
      target: aiService.properties.endpoints['Content Safety']
      metadata: {
        ApiVersion: '2023-07-01-preview'
        ApiType: 'azure'
        ResourceId: aiService.id
      }
      credentials: {
        key: aiService.listKeys().key1
      }
    }
  }


  resource searchConnection 'connections' =
    if (!empty(aiSearchName)) {
      name: aiSearchConnectionName
      properties: {
        category: 'CognitiveSearch'
        authType: 'ApiKey'
        isSharedToAll: true
        target: 'https://${search.name}.search.windows.net/'
        credentials: {
          key: !empty(aiSearchName) ? search.listAdminKeys().primaryKey : ''
        }
      }
    }
}

resource aiService 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = {
  name: aiServiceName
}



resource search 'Microsoft.Search/searchServices@2021-04-01-preview' existing =
  if (!empty(aiSearchName)) {
    name: aiSearchName
  }

output name string = hub.name
output id string = hub.id
output principalId string = hub.identity.principalId

// output aiServicesConnectionNames array = [for service in aiServicesNames: '${service}-connection']
// output aiServicesConnectionIds array = [for aiService in aiServicesNames: resourceId('Microsoft.CognitiveServices/accounts', aiService.id)]
// output aiServiceResourceIds array = [for aiService in aiServicesNames: resourceId('Microsoft.CognitiveServices/accounts', aiService.id)]
