// Per-region Azure OpenAI deployments for regional inference latency probing.
//
// Creates one Cognitive Services (kind=OpenAI) account per region, each with a
// single-region Standard deployment of the configured model. Standard deployments
// are pay-per-token with no idle/hourly cost, and a single-region (non-global) SKU
// processes requests in the account's region, which is what makes the measured
// latency attributable to that region.
//
// Deployed at resource group scope. The resource group's location is unrelated to
// the per-account locations created here.

@description('Azure regions to deploy the model into for latency probing.')
param regions array = [
  'eastus'
  'westus3'
  'swedencentral'
  'uksouth'
  'australiaeast'
  'japaneast'
]

@description('OpenAI model name to deploy.')
param modelName string = 'gpt-4o'

@description('OpenAI model version to deploy.')
param modelVersion string = '2024-11-20'

@description('Standard deployment capacity in thousands of tokens per minute (TPM).')
param deploymentCapacity int = 10

@description('Object ID (principal ID) of the identity that runs the probe, granted Cognitive Services OpenAI User.')
param probePrincipalId string = ''

@description('Deployment name used for the model; the probe targets this name.')
param deploymentName string = 'gpt-4o'

var namePrefix = 'azwatch-lat'
// Cognitive Services OpenAI User: read-only data-plane inference access.
var openAiUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'

resource accounts 'Microsoft.CognitiveServices/accounts@2024-10-01' = [
  for region in regions: {
    name: '${namePrefix}-${region}'
    location: region
    kind: 'OpenAI'
    sku: {
      name: 'S0'
    }
    properties: {
      customSubDomainName: '${namePrefix}-${region}-${uniqueString(resourceGroup().id, region)}'
      publicNetworkAccess: 'Enabled'
      disableLocalAuth: true
    }
  }
]

resource deployments 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = [
  for (region, index) in regions: {
    parent: accounts[index]
    name: deploymentName
    sku: {
      name: 'Standard'
      capacity: deploymentCapacity
    }
    properties: {
      model: {
        format: 'OpenAI'
        name: modelName
        version: modelVersion
      }
    }
  }
]

resource roleAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for (region, index) in regions: if (!empty(probePrincipalId)) {
    name: guid(accounts[index].id, probePrincipalId, openAiUserRoleId)
    scope: accounts[index]
    properties: {
      roleDefinitionId: subscriptionResourceId(
        'Microsoft.Authorization/roleDefinitions',
        openAiUserRoleId
      )
      principalId: probePrincipalId
      principalType: 'ServicePrincipal'
    }
  }
]

@description('Map of region to the account endpoint and deployment name for the probe.')
output targets array = [
  for (region, index) in regions: {
    region: region
    endpoint: accounts[index].properties.endpoint
    deployment: deploymentName
    model: modelName
  }
]
