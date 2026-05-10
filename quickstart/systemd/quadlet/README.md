# Thaum Podman Quadlet quickstart

This path deploys Thaum with Podman Quadlet, systemd encrypted credentials, and **localhost-only** exposure on the host.

- Config mounted at `/etc/thaum`
- Logs persisted at `/var/log/thaum`
- App data (including bundled PostgreSQL under `postgresql/data` and optional SQLite files) persisted at `/var/lib/thaum`
- Secrets loaded with systemd encrypted credentials and referenced as `secret:name` in config
- Root-only mounted credentials are staged to a non-root tmpfs directory and exported as `CREDENTIALS_DIRECTORY`
- Gunicorn binds **`127.0.0.1:5165`** inside the container; the host publishes **`127.0.0.1:5165:5165`** only (not `0.0.0.0`)

A reverse proxy on the **same host** can forward to `http://127.0.0.1:5165`. For nginx talking to Thaum over a **Unix domain socket** (stronger isolation on multi-service hosts), use [containerless](../containerless/README.md) instead.

## 1) Prerequisites

- Podman with Quadlet support
- systemd with `systemd-creds`
- A Thaum container image:
  - **Published (CI)**: pull from GitHub Container Registry, e.g. `podman pull ghcr.io/gemstone-software-dev/thaum:latest` (default in [`thaum.container`](thaum.container)). Other tags (`:devel`, `:edge` / `:edge-<branch>`, `:<version>`) are described in [README.md](../../../README.md) “Container images (CI)”.
  - **Local build**: from the repo root, `podman build -t localhost/thaum:local .` and set `Image=localhost/thaum:local` in [`thaum.container`](thaum.container) instead of the GHCR line.

## 2) Create local config

Copy the example config and edit non-secret values:

- [`../thaum.conf.example`](../thaum.conf.example)

Install it as `/etc/thaum/thaum.conf` (or another directory you mount to `/etc/thaum`).

Secret-backed keys in this example:

- `[server.database].db_url = "secret:thaum-db-url"` (optional if you omit `db_url` in config and use bundled PostgreSQL; see comments in [`../thaum.conf.example`](../thaum.conf.example))
- `[server.database].database_vault_passphrase = "secret:thaum-db-passphrase"`
- `[connections.example-atlassian].api_token = "secret:atlassian-api-token"` and matching keys in `[defaults.alert.jira]` (same token secret; see [docs/Atlassian-Jira.md](../../../docs/Atlassian-Jira.md))
- `[bots.database].token = "secret:webex-token-database"` (credential IDs use lowercase **kebab-case** so names stay valid if you reuse them as [Azure Key Vault](https://learn.microsoft.com/en-us/azure/key-vault/general/about-keys-secrets-certificates#object-types) or [Azure Container Apps](https://learn.microsoft.com/en-us/cli/azure/containerapp/secret?view=azure-cli-latest#az-containerapp-secret-set) secret names; ACA names are lowercase-only and at most 20 characters)

## 3) Create encrypted credentials

Run:

```bash
sudo ./quickstart/systemd/scripts/setup-systemd-credentials.sh
```

The script prompts for each value and writes encrypted credentials to:

- `/etc/credstore.encrypted/thaum-db-url` (optional: press Enter to skip if config omits `db_url`; align the service drop-in)
- `/etc/credstore.encrypted/thaum-db-passphrase`
- `/etc/credstore.encrypted/atlassian-api-token`
- `/etc/credstore.encrypted/webex-token-database`

## 4) Install Quadlet files

Copy these files to `/etc/containers/systemd/`:

- `quickstart/systemd/quadlet/thaum.container`
- `quickstart/systemd/quadlet/thaum-data.volume`
- `quickstart/systemd/quadlet/thaum-log.volume`

The `thaum.container` example includes:

- `Volume=%d:/run/secrets:ro` to mount systemd credentials in the container (root-readable source).
- `Mount=type=tmpfs,destination=/mycreds,noswap` and `Environment=THAUM_CREDS_DIR=/mycreds` for runtime staging.

At startup, `docker/entrypoint.sh` copies secret files from `/run/secrets` or `/var/run/secrets` into `THAUM_CREDS_DIR/thaum`, fixes ownership to `thaum`, and exports `CREDENTIALS_DIRECTORY` to the staged path.

Then ensure `/etc/thaum/thaum.conf` exists and reload systemd:

```bash
sudo systemctl daemon-reload
```

## 5) Load encrypted credentials into the service

Install the drop-in from:

- `quickstart/systemd/quadlet/thaum.service.credentials.conf.example`

to:

- `/etc/systemd/system/thaum.service.d/credentials.conf`

Then reload:

```bash
sudo systemctl daemon-reload
```

## 6) Start and verify

```bash
sudo systemctl enable --now thaum.service
sudo systemctl status thaum.service
sudo journalctl -u thaum.service -n 100 --no-pager
```

Restart policy in the example is fail-fast for show-stoppers and retry for transient failures:

- `Restart=on-failure` (not `always`)
- `RestartPreventExitStatus=10 11 12 40` (reserved permanent-failure codes)
- `StartLimitIntervalSec=300` + `StartLimitBurst=5` (rate-limit rapid loops)

This is important for multi-worker Gunicorn: restart decisions happen at the service/master process boundary, not per worker.

Inspect effective restart settings:

```bash
sudo systemctl show thaum.service \
  -p Restart \
  -p RestartPreventExitStatus \
  -p StartLimitIntervalUSec \
  -p StartLimitBurst
```

Validate unit syntax after changes:

```bash
sudo systemd-analyze verify /etc/containers/systemd/thaum.container
```

Verify staged credentials inside the running container:

```bash
sudo podman exec thaum sh -lc 'echo "$CREDENTIALS_DIRECTORY"; ls -l "$CREDENTIALS_DIRECTORY"'
```

If you enable file logging (`[logging] file = true`), logs are written to `/var/log/thaum/thaum.log`.
