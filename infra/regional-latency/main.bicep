// Per-region Azure OpenAI deployments for regional inference latency probing.
//
// Creates one Cognitive Services (kind=OpenAI) account per region (the union of all
// model regions), and a single-region Standard deployment of each configured model in
// the regions that model supports. Standard deployments are pay-per-token with no
// idle/hourly cost, and a single-region (non-global) SKU processes requests in the
// account's region, which is what makes the measured latency attributable to that
// region.
//
// Deployed at resource group scope. The resource group's location is unrelated to the
// per-account locations created here.

@description('Models to deploy. Each model lists the regions it supports as single-region Standard. Accounts are created for the union of all model regions.')
param models array = [
  {
    name: 'gpt-4o'
    version: '2024-11-20'
    deploymentName: 'gpt-4o'
    regions: [
      'eastus'
      'westus3'
      'swedencentral'
      'uksouth'
      'australiaeast'
      'japaneast'
    ]
  }
  {
    name: 'gpt-5.1'
    version: '2025-11-13'
    deploymentName: 'gpt-5.1'
    regions: [
      'eastus'
      'westus3'
      'swedencentral'
    ]
  }
]

@description('Standard deployment capacity in thousands of tokens per minute (TPM).')
param deploymentCapacity int = 10

@description('Object ID (principal ID) of the identity that runs the probe, granted Cognitive Services OpenAI User.')
param probePrincipalId string = ''

var namePrefix = 'azwatch-lat'
// Cognitive Services OpenAI User: read-only data-plane inference access.
var openAiUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'

// Union of every region any model targets; one account is created per unique region.
var regions = union(flatten(map(models, m => m.regions)), [])

// Flattened (model, region) pairs; one deployment is created per pair.
var modelDeployments = flatten(
  map(models, m => map(m.regions, r => {
    region: r
    name: m.name
    version: m.version
    deploymentName: m.deploymentName
  }))
)

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

// Deployments under the same account must be created serially.
@batchSize(1)
resource deployments 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = [
  for pair in modelDeployments: {
    parent: accounts[indexOf(regions, pair.region)]
    name: pair.deploymentName
    sku: {
      name: 'Standard'
      capacity: deploymentCapacity
    }
    properties: {
      model: {
        format: 'OpenAI'
        name: pair.name
        version: pair.version
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

@description('Per (model, region) probe targets: region, account endpoint, deployment name, and model.')
output targets array = [
  for pair in modelDeployments: {
    region: pair.region
    endpoint: accounts[indexOf(regions, pair.region)].properties.endpoint
    deployment: pair.deploymentName
    model: pair.name
  }
]
