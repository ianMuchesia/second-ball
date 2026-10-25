# infra

Azure Container Apps, judge mode: one container serves a recorded run bundle
and the built screen. No model calls, no secrets, no Kafka or Postgres (live
mode runs locally: `make up`, `make live`). The image is public on GitHub
Container Registry (GHCR): no Azure registry to pay for and no pull
credentials. `main.bicep` creates a Log Analytics workspace, the Container
Apps environment, the app (HTTPS only, health probes on `/api/health`,
Producer writes off) and a monthly cost budget with email alerts at 50% and
80% spent and 100% forecast.

Validate: `make infra` (compiles `main.bicep`).

## 1. Build and push the image (Ian, from this folder)

`runs/demo-foundry-2` is git-ignored, so the image is built here, where the
recording is; `.dockerignore` keeps `.env` and every other run out of it.
Pushing needs a GitHub token with `write:packages` (Settings → Developer
settings → Personal access tokens); type it at the prompt, never in a file.

```sh
IMAGE=ghcr.io/ianmuchesia/second-ball:demo-foundry-2
docker build --build-arg RUN=demo-foundry-2 -t $IMAGE .
read -rs GHCR_TOKEN && echo "$GHCR_TOKEN" | docker login ghcr.io -u ianMuchesia --password-stdin && unset GHCR_TOKEN
docker push $IMAGE
docker logout ghcr.io
```

Then make it public, once: GitHub → your profile → Packages → second-ball →
Package settings → Change visibility → Public. Check that anyone can pull it:
`docker pull $IMAGE` (logged out).

## 2. Deploy (Ian, logged in with `az login`)

```sh
RG=second-ball
EMAIL=you@example.com
az group create -n $RG -l southafricanorth
az deployment group create -g $RG -f infra/main.bicep -p budgetEmails="['$EMAIL']"
az deployment group show -g $RG -n main --query properties.outputs.url.value -o tsv
```

A new image under the same tag: `az containerapp update -g $RG -n secondball
--image $IMAGE` starts a new revision that pulls it.

After judging: `-p minReplicas=0` (no running replica, a cold start on the
next visit), or `az group delete -n $RG` to remove everything.
