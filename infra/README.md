# infra

Azure Container Apps, judge mode: one container serves a recorded run bundle
and the built screen. No model calls, no secrets, no Kafka or Postgres (live
mode runs locally: `make up`, `make live`). `main.bicep` creates a Log
Analytics workspace, a container registry (pulled with a managed identity, no
password), the Container Apps environment, the app (HTTPS only, health probes
on `/api/health`, Producer writes off) and a monthly cost budget with email
alerts at 50% and 80% spent and 100% forecast.

Validate: `make infra` (compiles `main.bicep`).

Deploy (Ian, logged in with `az login`; resource group in southafricanorth):

```sh
RG=second-ball
EMAIL=you@example.com
az group create -n $RG -l southafricanorth

# 1. Registry, identity, logs, environment, budget (no app yet).
az deployment group create -g $RG -f infra/main.bicep \
  -p deployApp=false budgetEmails="['$EMAIL']"
ACR=$(az deployment group show -g $RG -n main --query properties.outputs.registryName.value -o tsv)

# 2. Build the image in the registry from this folder (.dockerignore keeps
#    .env and every other run out of the upload).
az acr build -r $ACR -t second-ball:demo-foundry-2 --build-arg RUN=demo-foundry-2 .

# 3. The app.
az deployment group create -g $RG -f infra/main.bicep \
  -p deployApp=true budgetEmails="['$EMAIL']"
az deployment group show -g $RG -n main --query properties.outputs.url.value -o tsv
```

After judging: `-p minReplicas=0` (no running replica, a cold start on the
next visit), or `az group delete -n $RG` to remove everything.
