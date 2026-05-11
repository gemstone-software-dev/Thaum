# Thaum release notes

## v0.7.0a2 (alpha 2) — 2026-05-07

**`pyproject.toml`** is **`0.7.0a2`**.

Second **0.7.x** alpha: high-priority chat alert command, secret-resolver coverage for Atlassian connection / Jira responder fields, and forward-port of the v0.6.1 base-URL handling.

### Highlights since v0.7.0a1

- **Chat — `alert!`** — New high-priority alert command in `thaum.handlers.ALERT_COMMAND_PATTERN`. Routed through `BaseAlertPlugin.trigger_alert(..., AlertPriority.HIGH)` and gated by per-bot `high_pri_on`; if disabled, the bot replies with a hint to use `alert`. Usage help lists `alert![: message]` only when `high_pri_on` is true.
- **Jira alert tags** — `build_trigger_alert_body` in `alerts/plugins/jira/payload.py` now adds `HighPriority` alongside `OverrideQuietHours` on high-priority alerts so JSM Ops routing rules can target either tag.
- **Atlassian / Jira — resolved secrets** — `connections.plugins.atlassian.AtlassianConnectionConfig` fields `site_url`, `cloud_id`, `org_id`, and `user` accept resolver prefixes (`OptionalResolvedSecret`); `lookup.plugins.atlassian.AtlassianLookupPluginConfig` matches. `alerts.plugins.jira.config.JiraAlertPluginConfig` `responders` is now `ResolvedStringList` so each entry resolves through `resolve_secret`. New helper `_resolved_list_entry` and aliases `ResolvedListEntry` / `ResolvedStringList` live in `thaum.types`. Schema-only mode (`config_schema_only`) preserves unresolved references.
- **Server / config (forward-port from v0.6.1)** — `[server].base_url` may be omitted in TOML when `THAUM_BASE_URL` is set; clearer precedence and URL candidate normalization in `thaum.types.ServerConfig` (`_resolve_base_url`, `_strip_base_url_candidate`). Quickstart READMEs, `sample.thaum.toml`, and `scripts/python/thaum_config_check.py` aligned (`--schema-check` when `base_url` is omitted). Covered by `tests/test_server_config_base_url.py`.

### Dependencies

**`gemstone_utils`** **`0.4.0`** from **PyPI** (see **`pyproject.toml`**, **`requirements.txt`**; **`GEMSTONE_UTILS_REF`** in **`Dockerfile`** passes this version for image builds).

### Upgrade from v0.7.0a1

- **pip / venv**: **`pip install -U .`** (or your lockfile workflow) to pick up **`0.7.0a2`**.
- **Containers**: rebuild or pull an image tagged **`0.7.0a2`** when published.

No manual schema migration is required (**`init_db`** creates ORM tables on startup).

### Alpha caveats

- Breaking changes may occur before **v0.7.0** stable.

---

## v0.7.0a1 (alpha 1) — 2026-05-04

**`pyproject.toml`** is **`0.7.0a1`**.

First **0.7.x** alpha: structured logging, fail-fast startup behavior, and **`handle`** replacing **`name`** in bot config.

- **Logging** — Optional JSON structured logs (`[logging]`, `logging.json.*`); **SPAM**-level diagnostics behind `THAUM_LOG_SPAM=1`; dependency **`python-json-logger`**.
- **Startup** — Irrecoverable failures (missing config file, `bootstrap()` errors including **`init_db`**, leader upstream preflight, Webex webhook registration at startup, and invalid plugin configs) log a traceback via **`thaum.fatal.fail_fast_fatal`** and SIGTERM the Gunicorn parent when applicable.
- **Breaking — bot config** — Per-bot **`name`** is renamed to **`handle`** (mention / @-label for the chat platform). There is no **`name`** alias; update every **`[bots.<id>]`** table and any code building bot config dicts.

### Upgrade from v0.6.0

- **pip / venv**: **`pip install -U .`** (or your lockfile workflow) to pick up **`0.7.0a1`**.
- **Containers**: rebuild or pull an image tagged **`0.7.0a1`** when published.

---

## v0.6.1 — 2026-05-06

Maintenance release. **`pyproject.toml`** is **`0.6.1`**.

### Changes since tag v0.6.0

- **Server / config** — **`[server].base_url`** may be omitted in TOML when **`THAUM_BASE_URL`** is set at runtime; clearer precedence and URL candidate normalization in **`thaum.types.ServerConfig`** (**`_resolve_base_url`**, **`_strip_base_url_candidate`**).
- **Docs / samples** — Azure GitHub and Kubernetes quickstart READMEs, **`sample.thaum.toml`**, and **`thaum_config_check.py`** wording aligned with env vs TOML **`base_url`** behavior (**`--schema-check`** when **`base_url`** is omitted).
- **Tests** — **`tests/test_server_config_base_url.py`** exercises server **`base_url`** resolution.

### Dependencies

Unchanged from **v0.6.0**: **`gemstone_utils`** **`v0.4.0rc1`** (**`pyproject.toml`**, **`requirements.txt`**, **`GEMSTONE_UTILS_REF`** in **`Dockerfile`**).

### Upgrade from v0.6.0

- **pip / venv**: **`pip install -U .`** (or your lockfile workflow) to pick up **`0.6.1`**.
- **Containers**: rebuild or pull an image tagged **`0.6.1`** when published.

No manual schema migration is required for the default layout (**`init_db`** creates ORM tables on startup).

---

## v0.6.0 — 2026-05-02

First **stable 0.6.x** release. **`pyproject.toml`** is **`0.6.0`**.

This line finalizes the **v0.6.0rc1** / **v0.6.0rc2** candidates and includes the post-RC changes listed below.

### Changes since tag v0.6.0rc2

- **Config resolution** — Refactored path resolution and error handling; `resolve_config_path()` uses `THAUM_CONFIG_FILE` (if set), then `/etc/thaum/thaum.toml`, `/etc/thaum/thaum.conf`, `./thaum.toml`, and `./thaum.conf`; startup fails fast if none exist. `.toml` is canonical for examples (`sample.thaum.toml`).
- **Samples** — Removed legacy `sample.config.toml`; sample handles in `sample.thaum.toml` use obvious placeholder names.
- **Azure** — Container Apps deployment configuration; Key Vault integration in documentation and scripts.
- **Containers** — Dockerfile and entrypoint updates for bundled PostgreSQL and Azure-oriented deployment.

### Highlights carried forward from the 0.6 RC line

- **Chat commands** — Usage lists **`on-call[: message]`** for alerting the on-call contact; **`alert`**, **`oncall`**, and **`on_call`** are accepted as synonyms.
- **Lookup** — `get_person_by_email` contract; **Atlassian** Jira user search and **LDAP/AD** mail search; internal **`_get_cached_person_by_email`**.
- **Connections** — Shared **`merge_connection_profile`**; **Jira** alert **`connection_ref`** merged in bootstrap.
- **Jira alerts** — Alias-aware mapping, sender-name handling, **alias** field lookup, messageless alerts, status-webhook **`roomId`** fixes.
- **Webex bot** — **`delete_message`**, room-title support, webhook URL normalization in pruning.
- **CI / containers** — **`:edge`** tracks prerelease and stable GitHub Releases (and manual **`main`** workflow).

### Dependencies

**`gemstone_utils`** is pinned to **`v0.4.0rc1`** from **`gemstone-software-dev/gemstone_utils`** on GitHub (see **`pyproject.toml`**, **`requirements.txt`**, **`GEMSTONE_UTILS_REF`** in **`Dockerfile`**).

### Upgrade from v0.6.0rc2 or earlier prereleases

- **pip / venv**: **`pip install -U .`** (or your lockfile workflow) to pick up **`0.6.0`**.
- **Containers**: rebuild or pull an image tagged **`0.6.0`** when published.

No manual schema migration is required for the default layout (**`init_db`** creates ORM tables on startup).

---

## v0.6.0rc1 (release candidate 1) — 2026-04 (superseded by v0.6.0)

**Packaging** for this line used **`0.6.0rc1`** so installs from an unreleased git checkout (e.g. `pip install .` from **`main`**) reported a distinct version from published packages such as **v0.3.0a1**.

**Version numbering.** While **`0.4.0.dev0`** was still the declared version, **`main`** accumulated debugging and refactors toward a working build that, in a stricter release cadence, would have shipped as the **0.5.0** line. No **0.5.x** tag was ever cut on **`main`**, so this prerelease jumps straight to **`0.6.0rc1`**. The prerelease style moves from **`aN` / `bN`** to **`rc`** to signal that the surface area is now treated as roughly **60% stable**—breaking changes are less likely before **0.6.0** stable, but not impossible.

### Highlights since v0.3.0a1

- **Lookup** — `get_person_by_email` contract: cache vs live resolution; **Atlassian** Jira user search and **LDAP/AD** mail search; internal **`_get_cached_person_by_email`**.
- **Connections** — Shared **`merge_connection_profile`**; **Jira** alert **`connection_ref`** merged in bootstrap (no plugin branch).
- **LDAP** — Optional **`platform_ids_ldap_attribute`** / **`platform_ids_format`** (`json` or multi-value delimited) for extra Thaum platform ids; **[`docs/LDAP-AD-lookup.md`](docs/LDAP-AD-lookup.md)**.
- **Jira alerts** — Alias-aware mapping and sender-name handling, **alias-based alert id lookup** (Jira **`alias`** field), **messageless** alert support, and status-webhook **`roomId`** resolution fixes.
- **Webex bot** — **`delete_message`** on **`BaseChatBot`** / **`WebexChatBot`**, room-title support, webhook URL normalization in webhook pruning.
- **Containers** — Docker entrypoint and supervisord refinements; PostgreSQL data-directory setup hardening.
- **CI / containers** — **`:edge`** updated on **prerelease** and **stable** GitHub Releases (and manual **`main`** workflow) so it tracks the current image.

### Dependencies

**`gemstone_utils`** is pinned to **`v0.4.0rc1`** and installed from **`gemstone-software-dev/gemstone_utils`** on GitHub (Git tag only; **not** yet on PyPI). See **`pyproject.toml`**, **`requirements.txt`**, and the **`GEMSTONE_UTILS_REF`** build-arg in **`Dockerfile`**.

### Upgrade from v0.3.0a1

- **pip / venv**: **`pip install -U .`** or **`-r requirements.txt`** to pick up **`gemstone_utils`** at **`v0.4.0rc1`**.
- **Containers**: rebuild or pull an image tagged **`0.6.0rc1`** when published; no manual schema migration required for the default layout (**`init_db`** creates any new ORM tables on startup).

### Release candidate caveats

- **v0.6.0** stable shipped **2026-05-02** (see section above); this RC section remains for historical context.

---

## v0.3.0a1 (alpha 1) — 2026-04-16

First **0.3.x** prerelease: Atlassian-aware lookup, shared connection profiles, and coordinated multi-worker bootstrap.

### Highlights

- **Connections (`connections.plugins.*`)** — Named **`[connections.<name>]`** profiles (initially **`atlassian`**: `site_url`, `cloud_id`, `org_id`, optional `user` / `api_token`). Validated via Pydantic; no runtime behavior beyond config merge.
- **Lookup merge** — **`[lookup.<plugin>].connection_ref`** merges a connection profile into lookup settings (connection first, plugin table wins on conflicts). Used by **`lookup.atlassian`** to share Cloud identity with other consumers.
- **`lookup.atlassian`** — **Public Teams API** (`api.atlassian.com`) for org teams (leader preload into identity cache without members); **POST** members + **Jira REST** `GET /rest/api/3/user` for account ids. Platform id key **`jira`** for compatibility with **`id:team:`** / **`id:person:`** and the Jira alert plugin. Optional **`leader_init_tasks_register`** preloads teams before **`initialize_bots`**.
- **Leader bootstrap** — After **`initialize_lookup_plugin`**, workers run election once: the **leader** runs registered **one-shot init tasks** (e.g. team preload); **non-leaders** wait on a **DB barrier** (`schema_leader_init_status`) until the leader finishes or reports failure. Configurable wait: **`[server.election].leader_init_wait_timeout_seconds`** (default **300**). **`create_app`** reuses the same election candidate id for the background leader loop (no second **`register_candidate`**).
- **HTTP timeouts** — **`thaum.http_timeouts`**: fractional **connect** timeout (**`HTTP_CONNECT_TIMEOUT`**, default **2.5** s) plus **read** timeout **`(connect, read)`** tuples for **`requests`** on Jira alert and Atlassian lookup paths (avoids hanging forever on stalled TCP while allowing slower JSON reads).

### Upgrade from v0.2.0a6

- **Database**: deploy with a shared app DB as today; new ORM table **`schema_leader_init_status`** is created on startup via **`init_db`** (no manual migration file required for the default layout).
- **Multi-worker**: non-leader processes block in bootstrap until the leader completes init tasks or the barrier wait times out; ensure **`[server.election]`** and DB connectivity match your deployment.
- **pip / venv**: **`pip install -U .`** or **`-r requirements.txt`**; **`gemstone_utils`** pin unchanged (**`v0.3.0a2`**).
- **Containers**: rebuild or pull an image tagged **`0.3.0a1`** when published; existing **`/var/lib/thaum`** volume usage is unchanged aside from new metadata rows.

### Alpha caveats

- Breaking changes may occur before **v0.3.0** stable.

---

## v0.2.0a6 (alpha 6) — 2026-04-13

- **Containers (bundled PostgreSQL)** — Unix socket directory moved from **`/run/thaum/postgres`** to **`/tmp/postgres`** so permission quirks on some hosts no longer block the app from connecting; existing clusters are migrated on startup via **`postgresql.auto.conf`**. Startup sequence still initializes the DB, runs **`pg_bootstrap`**, then hands off to **supervisord**.
- **Docker entrypoint** — **`HOME=/home/thaum`** so gunicorn does not treat **`/root`** as home when dropping privileges. When **`THAUM_CREDS_DIR`** is set, credentials from **`/run/secrets`** / **`/var/run/secrets`** are copied into a **thaum**-owned tree and **`CREDENTIALS_DIRECTORY`** is set for **`resolve_secret`**. Aligns with **systemd** / **Quadlet** credential layouts.
- **Imports** — Refactors in **`thaum.__init__`** and bot loading remove circular import issues during startup.
- **Database** — **`db_bootstrap`** handles PostgreSQL URLs more robustly when building the engine.
- **Logging** — **`LogConfig`** normalizes configured log levels for consistent behavior.
- **Webex** — **`WebexChatBot`** webhook registration path refactored for clarity.
- **Operations** — With **`GET /health`** returning **200** in your deployment (liveness), load balancers and platform health checks can use the documented probe paths; **`GET /ready`** remains the database readiness check.

### Upgrade from v0.2.0a5

- **Containers**: rebuild or pull the **`0.2.0a6`** image; existing **`/var/lib/thaum`** volumes remain compatible (socket path is updated in config on startup where needed).
- **pip / venv**: no dependency pin changes from **a5**; upgrade for the packaging version and runtime fixes above.

### Alpha caveats

- Breaking changes may occur before **v0.2.0** stable.

---

## v0.2.0a5 (alpha 5) — 2026-04-12

- **Containers (bundled PostgreSQL)** — Debian installs server programs under **`/usr/lib/postgresql/<major>/bin/`**, so **`initdb`** / **`pg_ctl`** / **`postgres`** were not always on the default **`PATH`** inside the image, and **`gosu postgres initdb`** could fail at startup. The image now adds **symlinks in `/usr/local/bin`** to those binaries (version discovered at build time), and **supervisord** runs **`/usr/local/bin/postgres`**. No change to **`PGDATA`**, sockets, or app config for bundled DB.

### Upgrade from v0.2.0a4

- **Containers**: rebuild or pull the **`0.2.0a5`** image; existing **`/var/lib/thaum`** volumes are compatible (same data layout as **a4**).
- **pip / venv**: no dependency changes from **a4**; upgrade only if you want the packaging version bump.

### Alpha caveats

- Breaking changes may occur before **v0.2.0** stable.

---

## v0.2.0a4 (alpha 4) — 2026-04-12

- **Documentation** — **[`docs/deployment-quickstarts.md`](docs/deployment-quickstarts.md)** indexes cloud and Kubernetes paths. New **Kubernetes** example manifests under **`quickstart/kubernetes/`**; **Azure App Service** (Linux container) + **GitHub Actions** guide under **`quickstart/cloud/azure/github/`**; **[`quickstart/cloud/README.md`](quickstart/cloud/README.md)** lists available cloud quickstarts.
- **Dependencies** — **`gemstone_utils`** is installed from **`gemstone-software-dev/gemstone_utils`** and pinned to **`v0.3.0a2`** (see **`pyproject.toml`** and **`requirements.txt`**).
- **CI / images** — README and release workflow clarify **`:devel`**, **`:latest`**, and **`:edge`** container tags (no change to application behavior).

### Upgrade from v0.2.0a3

- **pip / venv**: if you install from the repo, **`pip install -U .`** (or **`-r requirements.txt`**) picks up the **`gemstone_utils`** URL and tag above.
- **Containers**: **`ghcr.io`** (or your registry) **`0.2.0a4`** and **`:devel`** images include the same dependency pin; no database or probe changes from **a3**.

### Alpha caveats

- Breaking changes may occur before **v0.2.0** stable.

---

## v0.2.0a3 (alpha 3) — 2026-04-12

- **HTTP probes** — **`GET /health`** returns **200** with JSON `{"status": "ok"}` for liveness (process can serve HTTP). **`GET /ready`** returns **200** after a **`SELECT 1`** against the configured app database, or **503** with `{"status": "unavailable", "reason": "database"}` if the check fails (readiness for load balancers and orchestrators).
- **Packaging** — **gunicorn** is listed in **`requirements.txt`** and **`pyproject.toml`** dependencies; the **Dockerfile** no longer installs it in a separate **`pip`** step (same image contents, single dependency path for container and **pip**/venv installs).

### Upgrade from v0.2.0a2

- **Container image**: no PostgreSQL layout change from **a2**. Configure probes to use **`/health`** (liveness) and **`/ready`** (readiness) on your app bind or reverse proxy path as needed.
- **pip / containerless venvs**: reinstall or **`pip install -U .`** (or **`-r requirements.txt`**) so **gunicorn** is installed from project metadata if you previously installed it manually.

### Alpha caveats

- Breaking changes may occur before **v0.2.0** stable.

---

## v0.2.0a2 (alpha 2) — 2026-04-11

Container image change: bundled PostgreSQL now uses **`PGDATA`** at **`/var/lib/thaum/postgresql/data`** and Unix sockets under **`/run/thaum/postgres`**, matching the default in **`thaum.db_bootstrap`** (`DEFAULT_PG_SOCKET_DIR`) and the **`/var/lib/thaum`** volume used by Podman quadlet quickstart. The image declares a single app data volume at **`/var/lib/thaum`** (replacing a separate **`/var/lib/postgresql/data`** volume).

### Upgrade from v0.2.0a1

- If you used **bundled** PostgreSQL with the **0.2.0a1** image, migrate the data directory from **`/var/lib/postgresql/data`** to **`/var/lib/thaum/postgresql/data`** inside your volume, or plan for a **fresh cluster** and restore from backup.
- If you **pinned** **`db_url`** with **`host=/var/run/postgresql`**, update it to **`host=/run/thaum/postgres`** (or rely on the default by omitting an explicit bundled URL).

### Alpha caveats

- Breaking changes may occur before **v0.2.0** stable.

---

## v0.2.0a1 (alpha 1) — 2026-04-11

First **0.2.x** prerelease. Development since **v0.1.0a1** included substantial refactors and new capabilities; the **0.2** line better matches that scope than another snapshot labeled as marching toward **0.1.0** stable.

### Highlights since v0.1.0a1

- **Database** — **PostgreSQL** support alongside the bundled layout; **`db_url`**-centric configuration (replacing earlier `db_spec`-style wiring), connection testing and validation, and integration with **gemstone_utils** for schema/bootstrap (including migration from earlier **emerald_utils** usage). Ongoing refinements to encryption, key handling, and lookup/bootstrap paths.
- **Plugins** — Dedicated **`plugins/`** layout for bots, lookups, and alerts; shared **`BasePlugin`** and clearer registry/config loading; **Jira** alert plugin split into focused modules with improved webhooks, status handling, and escalation-related configuration.
- **Security / HTTP** — **Webhook bearer** token lifecycle with database-backed warnings; **signed admin API** for runtime log level (see [docs/admin-log-level.md](docs/admin-log-level.md)).
- **Ops** — Multi-stage **Dockerfile**, **README** notes on **GHCR** publishing via CI, **quickstart** and **systemd** samples (including credential-oriented patterns), optional **file logging** and structured logging improvements.
- **Config** — Stricter **Pydantic** validation, **`ResolvedSecret`** and related patterns for secrets in config (e.g. database URL), and tooling/scripts for configuration checks.

### Alpha caveats

- Breaking changes may occur before **v0.2.0** stable.
- Validate behavior in your environment before relying on Thaum for critical on-call paths.

### Thanks

Feedback and patches are welcome as Thaum moves toward a stable **0.2** line.

---

## v0.1.0a1 (alpha 1) — 2026-04-05

First public **alpha** tag. This release is intended for early adopters who can tolerate rough edges while the API, packaging story, and operations guides stabilize.

### What Thaum is

Thaum connects chat platforms to on-call style alerting. It ships with a **Webex** bot driver and **Jira Service Management Ops** alerting; lookup and alert surfaces are **plugin-based** so other backends (Teams, PagerDuty, and so on) can be added without rewriting the core.

### Highlights in this alpha

- **Configuration** — `config.toml` with typed **Pydantic** models (`ServerConfig`, `LogConfig`, per-bot and plugin configs).
- **HTTP surface** — Flask app (`web.py`), bot webhooks, and optional **signed admin API** for runtime root log level (`POST /{route_id}/log-level`); see [docs/admin-log-level.md](docs/admin-log-level.md).
- **Database** — Shared app database (SQLAlchemy / Gemstone); optional field encryption and DEK rotation hooks.
- **Multi-worker** — Leader election so only the leader registers Webex webhooks when multiple processes run.
- **Logging** — ISO8601-aware formatters, custom levels (including SPAM for full diagnostics), optional **file logging** (`[logging].file`) with timed rotation and strict opt-in semantics; stdout remains the default for container-style deployments.
- **Documentation** — Architecture and style guides live under [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/STYLE_GUIDE.md](docs/STYLE_GUIDE.md).

### Documentation layout

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — bootstrap sequence, configuration model, logging, import rules.
- [docs/STYLE_GUIDE.md](docs/STYLE_GUIDE.md) — project conventions for Python and tests.
- [docs/admin-log-level.md](docs/admin-log-level.md) — signed log-level admin API.

### Alpha caveats

- Breaking changes may occur before **v0.1.0** stable.
- Production hardening (packaging, upgrade paths, and broader platform coverage) is still evolving; validate behavior in your environment before relying on it for critical on-call paths.

### Thanks

Feedback and patches are welcome as Thaum moves toward a stable **0.1** line.
