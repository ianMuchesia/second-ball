// Second Ball on Azure Container Apps (judge mode: one recorded run, no model
// calls, no secrets). Two passes (infra/README.md):
//   1. deployApp=false: registry, identity, logs, environment, budget;
//   2. push the image to the registry, then deployApp=true: the app.
targetScope = 'resourceGroup'

@description('Region; South Africa North is closest to Nairobi (DECISIONS.md).')
param location string = resourceGroup().location

@description('Prefix for resource names (lowercase letters and digits).')
@minLength(3)
@maxLength(12)
param name string = 'secondball'

@description('Create the container app (pass 2, once the image is in the registry).')
param deployApp bool = false

@description('Image tag in the registry, e.g. second-ball:demo-foundry-2.')
param imageTag string = 'second-ball:demo-foundry-2'

@description('Replicas kept running: 1 while judges may visit (no cold start), 0 afterwards.')
@minValue(0)
@maxValue(1)
param minReplicas int = 1

@description('Monthly cost budget for this resource group, in the billing currency.')
param budgetAmount int = 20

@description('Who gets the budget alerts.')
param budgetEmails array

@description('First day of the month the budget starts (yyyy-MM-01).')
param budgetStart string = '2026-10-01'

var suffix = uniqueString(resourceGroup().id)
var acrPullRole = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '7f951dda-4ed3-4680-a7ca-43fe172d538d'
)

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${name}-logs'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: '${name}${suffix}'
  location: location
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false } // pulled with the identity below, no password
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${name}-app'
  location: location
}

resource pull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, identity.id, acrPullRole)
  scope: registry
  properties: {
    roleDefinitionId: acrPullRole
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${name}-env'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

resource app 'Microsoft.App/containerApps@2024-03-01' = if (deployApp) {
  name: name
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false // HTTPS only
      }
      registries: [
        {
          server: registry.properties.loginServer
          identity: identity.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'second-ball'
          image: '${registry.properties.loginServer}/${imageTag}'
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            // Also set in the image; repeated so the public setting is visible here.
            { name: 'PRODUCER_WRITES', value: 'off' }
            { name: 'RUNS_DIR', value: '/app/runs' }
          ]
          probes: [
            {
              type: 'Liveness'
              httpGet: { path: '/api/health', port: 8000 }
              initialDelaySeconds: 10
              periodSeconds: 30
            }
            {
              type: 'Readiness'
              httpGet: { path: '/api/health', port: 8000 }
              initialDelaySeconds: 5
              periodSeconds: 10
            }
          ]
        }
      ]
      scale: { minReplicas: minReplicas, maxReplicas: 1 }
    }
  }
  dependsOn: [pull]
}

resource budget 'Microsoft.Consumption/budgets@2023-05-01' = {
  name: '${name}-monthly'
  properties: {
    category: 'Cost'
    amount: budgetAmount
    timeGrain: 'Monthly'
    timePeriod: { startDate: budgetStart }
    notifications: {
      actual50: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 50
        thresholdType: 'Actual'
        contactEmails: budgetEmails
      }
      actual80: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 80
        thresholdType: 'Actual'
        contactEmails: budgetEmails
      }
      forecast100: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 100
        thresholdType: 'Forecasted'
        contactEmails: budgetEmails
      }
    }
  }
}

output registryName string = registry.name
output registryServer string = registry.properties.loginServer
output url string = deployApp ? 'https://${app!.properties.configuration.ingress.fqdn}' : ''
