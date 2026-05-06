# Azure Container Apps + GitHub Actions

Deploy Thaum as a **single** container app on **Azure Container Apps** using an image from a **container registry** (public [GHCR](https://github.com/orgs/gemstone-software-dev/packages) or your own **ACR** after [GitHub Actions](deploy.yml.example) builds and pushes). This quickstart does not use `az containerapp up --source .`; it follows the registry-based pattern in [Tutorial: Build and deploy your app to Azure Container Apps (ACR-remote)](https://learn.microsoft.com/en-us/azure/container-apps/tutorial-code-to-cloud?tabs=bash%2Ccsharp&pivots=acr-remote).

- General Thaum quickstart: [QUICKSTART.md](../../../QUICKSTART.md)
- Example TOML (adjust for Azure): [systemd/thaum.conf.example](../../../systemd/thaum.conf.example)
- Container image tags (GHCR, etc.): [README.md](../../../../README.md) (section *Container images (CI)*)

Microsoft references for secrets and Key Vault:

- [Manage secrets in Azure Container Apps](https://learn.microsoft.com/en-us/azure/container-apps/manage-secrets?tabs=azure-cli) (`keyvaultref`, `secretref`, `--secret-volume-mount`)
- [`az keyvault secret set`](https://learn.microsoft.com/en-us/cli/azure/keyvault/secret?view=azure-cli-latest#az-keyvault-secret-set)

## What you get

| Aspect | Behavior |
|--------|----------|
| **Topology** | One resource group, one Container Apps environment, one Container App |
| **Image** | Pulled from **GHCR** (simplest if the image is public) or **ACR** (typical with a deploy repo and CI) |
| **Default database** | **Bundled PostgreSQL** inside the official Thaum image (`THAUM_EXTERNAL_DB` unset or false). No managed database cost. |
| **Data durability** | Container filesystem is **ephemeral**. The bundled Postgres store can **lose data** on revision change or restart unless you add persistent storage or switch to an external database. |
| **Optional upgrade** | **Azure Database for PostgreSQL** (or other managed Postgres): set **`THAUM_EXTERNAL_DB=true`**, set **`[server.database].db_url`** in your TOML (and supply credentials via Key Vault as below). See [Optional: external managed Postgres](#optional-external-managed-postgres). |

## Prerequisites

- Azure subscription and rights to create resource groups, Container Apps, Key Vault, and (for ACR path) Azure Container Registry
- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) (`az login`)
- A GitHub repository for **your** deployment assets (Dockerfile + config + workflow) if you use the ACR path

Copy the example files from this directory into that repo:

- [Dockerfile.example](Dockerfile.example) → `Dockerfile`
- [deploy.yml.example](deploy.yml.example) → `.github/workflows/deploy.yml`
- [scripts/keyvault-uri.ps1.example](scripts/keyvault-uri.ps1.example) → `scripts/keyvault-uri.ps1` (optional)
- [scripts/set-keyvault-secret-from-file.ps1.example](scripts/set-keyvault-secret-from-file.ps1.example) → `scripts/set-keyvault-secret-from-file.ps1` (optional)

## 1. Azure CLI setup

```powershell
$SUBSCRIPTION = "<your-subscription-id-or-name>"
$LOCATION = "eastus"
$RESOURCE_GROUP = "thaum-rg"
$ENVIRONMENT = "thaum-env"

az account set --subscription $SUBSCRIPTION
az upgrade
az extension add --name containerapp --upgrade --allow-preview true
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.OperationalInsights
az group create --name $RESOURCE_GROUP --location $LOCATION

az containerapp env create `
  --name $ENVIRONMENT `
  --resource-group $RESOURCE_GROUP `
  --location $LOCATION
```

## 2. Choose an image source

### Path A: Public image from GHCR

If your organization pulls **public** images from GHCR without authentication, create the app with `--image` pointing at a pinned tag (see upstream [README.md](../../../../README.md)).

```powershell
$APP_NAME = "thaum-app"
$IMAGE = "ghcr.io/gemstone-software-dev/thaum:<version-tag>"

az containerapp create `
  --name $APP_NAME `
  --resource-group $RESOURCE_GROUP `
  --environment $ENVIRONMENT `
  --image $IMAGE `
  --ingress external `
  --target-port 5165
```

If the image is **private**, configure registry credentials or managed identity for your registry per [Container Apps registries](https://learn.microsoft.com/en-us/azure/container-apps/containers#container-registries); that is outside this minimal quickstart.

### Path B: Azure Container Registry + GitHub Actions

1. Create a registry (names must be globally unique and alphanumeric):

   ```powershell
   $ACR_NAME = "thaumacr<unique>"
   az acr create --resource-group $RESOURCE_GROUP --name $ACR_NAME --sku Basic --admin-enabled true
   ```

2. One-time: create the Container App with the **first** image you will push (or a public placeholder), same ingress as Path A, using `myregistry.azurecr.io/<repo>:tag` after your pipeline has pushed at least once—or create the app in the portal and point CI at `az containerapp update --image` as in [deploy.yml.example](deploy.yml.example).

3. Wire CI: copy [deploy.yml.example](deploy.yml.example), set variables (`ACR_LOGIN_SERVER`, `IMAGE_NAME`, `AZURE_RESOURCE_GROUP`, `AZURE_CONTAINERAPP_NAME`), and push; each run builds, schema-checks, pushes to ACR, and updates the app image. This matches the **ACR-remote** tutorial flow ([link](https://learn.microsoft.com/en-us/azure/container-apps/tutorial-code-to-cloud?tabs=bash%2Ccsharp&pivots=acr-remote)).

## 3. Secrets: Key Vault + `keyvaultref` + volume mount

Avoid putting production secret values in Container Apps directly. Store them in **Azure Key Vault**, then reference them from the app using **`keyvaultref:`** as described in [Manage secrets](https://learn.microsoft.com/en-us/azure/container-apps/manage-secrets?tabs=azure-cli).

**Important:** On `az containerapp create`, Key Vault references in `--secrets` require a **user-assigned** managed identity—the system-assigned identity is not available until after the app exists ([Microsoft Learn note](https://learn.microsoft.com/en-us/azure/container-apps/manage-secrets?tabs=azure-cli)).

### 3a. Key Vault and secret values

Create a vault and write each secret from a file (avoids secrets on the command line). Example:

```powershell
$VAULT_NAME = "thaum-kv-<unique>"
az keyvault create --name $VAULT_NAME --resource-group $RESOURCE_GROUP --location $LOCATION

# Example: write token to a UTF-8 file, then upload (see scripts/set-keyvault-secret-from-file.ps1.example); delete the file afterward if needed
az keyvault secret set --vault-name $VAULT_NAME --name webex_token_database --file .\webex_token_database.txt
```

Use one Key Vault secret name per Thaum `secret:<key>` file you need under `/run/secrets` (names must match; see [sample.thaum.toml](../../../../sample.thaum.toml)).

### 3b. User-assigned identity and Key Vault access

```powershell
$UAMI_NAME = "thaum-aca-secrets"
$UAMI_ID = az identity create --name $UAMI_NAME --resource-group $RESOURCE_GROUP --location $LOCATION --query id -o tsv
$KV_ID = az keyvault show --name $VAULT_NAME --resource-group $RESOURCE_GROUP --query id -o tsv

$UAMI_PRINCIPAL = az identity show --ids $UAMI_ID --query principalId -o tsv
az role assignment create `
  --role "Key Vault Secrets User" `
  --assignee-object-id $UAMI_PRINCIPAL `
  --assignee-principal-type ServicePrincipal `
  --scope $KV_ID
```

### 3c. Key Vault secret URI

For each secret, the URI passed to `keyvaultref` is either:

- `https://<vault>.vault.azure.net/secrets/<name>` (latest version), or
- `https://<vault>.vault.azure.net/secrets/<name>/<version-id>` (pinned version)

You can print the vault base URI with [scripts/keyvault-uri.ps1.example](scripts/keyvault-uri.ps1.example) and append `/secrets/<name>`.

### 3d. Attach identity, define Key Vault–backed app secrets, mount files, set `THAUM_CREDS_DIR`

Thaum runs as user `thaum`. Orchestrator-mounted secret files are often root-readable only; set **`THAUM_CREDS_DIR`** so [docker/entrypoint.sh](../../../../docker/entrypoint.sh) copies `/run/secrets` into a tmpfs directory the app user can read.

Use **`--secret-volume-mount "/run/secrets"`** to mount **all** app-level secrets as files under `/run/secrets` without a YAML file ([Manage secrets — mounting secrets in a volume](https://learn.microsoft.com/en-us/azure/container-apps/manage-secrets?tabs=azure-cli#mounting-secrets-in-a-volume)). Each file name equals the **Container Apps secret name**; keep those names aligned with `secret:<key>` in `thaum.toml`.

**Caveat:** If you need **only a subset** of secrets mounted or **custom filenames** inside the volume, Microsoft documents using **YAML** (`--yaml`) instead of `--secret-volume-mount`.

Example (add `--user-assigned` and `--secrets` / `--secret-volume-mount` / `--set-env-vars` to `create`, or use `az containerapp update` on an existing app):

```powershell
$APP_NAME = "thaum-app"
$SECRET_URI_DB = "https://$VAULT_NAME.vault.azure.net/secrets/webex_token_database"

az containerapp update `
  --name $APP_NAME `
  --resource-group $RESOURCE_GROUP `
  --user-assigned $UAMI_ID `
  --secrets "webex_token_database=keyvaultref:$SECRET_URI_DB,identityref:$UAMI_ID" `
  --secret-volume-mount "/run/secrets" `
  --set-env-vars "THAUM_CREDS_DIR=/tmp/thaum-creds"
```

Repeat additional `keyvaultref:` pairs in `--secrets` for each bot token (and any other file-backed secrets). If `create` is used instead of `update`, include the same flags together with `--image`, `--environment`, `--ingress`, and `--target-port 5165`.

In **`thaum.toml`**, use `secret:webex_token_database` (etc.) so `resolve_secret` reads the file copied into `CREDENTIALS_DIRECTORY`.

## Health checks

Thaum exposes:

- `GET /health` — process liveness
- `GET /ready` — database readiness (`SELECT 1`)

Configure Container Apps probes to hit `/ready` (or `/health`) on port **5165**.

## Configuration file

1. Start from [systemd/thaum.conf.example](../../../systemd/thaum.conf.example).
2. Set **`[server].base_url`** to your Container App’s public URL, **or** omit `base_url` and set **`THAUM_BASE_URL`** at runtime (env overrides TOML when both are set).
3. Save it in your deploy repo as **`thaum.toml`**. [Dockerfile.example](Dockerfile.example) copies it to **`/etc/thaum/thaum.toml`**.

Keep sensitive values out of Git: use **`secret:<key>`** with the Key Vault–backed mount flow above (not inline tokens in `az containerapp secret set` for production).

### `THAUM_BASE_URL` in CI

Pipelines often set **`THAUM_BASE_URL`** so the public URL does not live in Git; it **overrides** `[server].base_url` when both are set. **`--schema-check`** in `thaum_config_check.py` may rely on **`THAUM_BASE_URL`** when `base_url` is omitted from TOML; see that script’s epilog in the main repo.

## Dockerfile (deploy repo)

Use [Dockerfile.example](Dockerfile.example):

- **`FROM`** a **pinned** upstream image (tag or digest), not only `:latest`.
- **`COPY`** your `thaum.toml` to `/etc/thaum/thaum.toml`.
- For **external Postgres**, set **`THAUM_EXTERNAL_DB=true`** and supply **`db_url`** (and secrets via Key Vault as above). See [ARCHITECTURE.md](../../../../docs/ARCHITECTURE.md).

## GitHub Actions

Copy [deploy.yml.example](deploy.yml.example) to `.github/workflows/deploy.yml`. The workflow builds and pushes the **image** only; **application secrets** stay in Key Vault and are wired with `keyvaultref` as in section 3 (not stored in GitHub Secrets for Thaum tokens unless you choose that separately).

- **`--schema-check`**: safe in CI without resolving secrets or hitting the database.
- **`--test-config`**: full validation + DB ping; run only where secrets and DB exist.

## Optional: external managed Postgres

1. Create a managed Postgres instance and a database/user for Thaum.
2. Set Container Apps environment variable **`THAUM_EXTERNAL_DB=true`**.
3. In your TOML, set **`[server.database].db_url`** (reference credentials via Key Vault–mounted files and `secret:` / `env:` as appropriate; do not commit passwords).
4. Redeploy. The container runs **Gunicorn only** (no bundled Postgres); see [Dockerfile](../../../../Dockerfile) and [docker/entrypoint.sh](../../../../docker/entrypoint.sh).

## Files in this directory

| File | Purpose |
|------|---------|
| [Dockerfile.example](Dockerfile.example) | `FROM` upstream Thaum image + `COPY` `thaum.toml` → `/etc/thaum/thaum.toml` |
| [deploy.yml.example](deploy.yml.example) | Build → schema-check → push to ACR → update Container App image |
| [scripts/keyvault-uri.ps1.example](scripts/keyvault-uri.ps1.example) | Print Key Vault `vaultUri` (build `keyvaultref` secret URIs) |
| [scripts/set-keyvault-secret-from-file.ps1.example](scripts/set-keyvault-secret-from-file.ps1.example) | Set a vault secret from a file via `az keyvault secret set --file` |
| [scripts/keyvault-uri.bat.example](scripts/keyvault-uri.bat.example) | Invoke the PowerShell URI script from cmd |
