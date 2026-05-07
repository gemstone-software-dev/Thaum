# SPDX-License-Identifier: MPL-2.0
# Copyright 2026 Clinton Bunch
# lookup/plugins/atlassian.py
"""Atlassian Cloud lookup: Public Teams API + Jira REST (accountId → user)."""
from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any, Dict, Iterator, List, Optional, Tuple

import requests
from pydantic import Field, model_validator
from requests.auth import HTTPBasicAuth

from lookup.base import BaseLookupPlugin, BaseLookupPluginConfig
from thaum.http_timeouts import timeout_pair
from thaum.types import LogLevel, OptionalResolvedSecret, ServerConfig, ThaumPerson, ThaumTeam

# Platform id key shared with Jira alert integration and BaseLookupPlugin.resolve_responder_refs.
_JIRA_PLATFORM_KEY = "jira"

ATLASSIAN_API_BASE = "https://api.atlassian.com"


class AtlassianLookupPluginConfig(BaseLookupPluginConfig):
    """
    Optional ``connection_ref`` merges ``[connections.<name>]`` (see :func:`lookup.factory.merge_lookup_connection_profile`).

    Requires ``site_url``, ``cloud_id``, ``org_id``, ``user``, and ``api_token`` after merge.
    """

    connection_ref: Optional[str] = None

    site_url: OptionalResolvedSecret = None
    cloud_id: OptionalResolvedSecret = None
    org_id: OptionalResolvedSecret = None
    user: OptionalResolvedSecret = None
    api_token: OptionalResolvedSecret = None

    teams_page_size: int = Field(default=50, ge=1, le=50, description="Public Teams API page size (max 50).")
    http_timeout_seconds: float = Field(
        default=30.0,
        description=(
            "Read-phase timeout for Atlassian HTTP responses (connect uses a short fractional timeout; "
            "see thaum.http_timeouts.HTTP_CONNECT_TIMEOUT)."
        ),
    )

    @model_validator(mode="after")
    def _require_atlassian_fields(self) -> AtlassianLookupPluginConfig:
        if not (self.site_url or "").strip():
            raise ValueError("lookup.atlassian requires site_url (or via connection_ref).")
        if not (self.cloud_id or "").strip():
            raise ValueError("lookup.atlassian requires cloud_id (or via connection_ref).")
        if not (self.org_id or "").strip():
            raise ValueError("lookup.atlassian requires org_id (or via connection_ref).")
        if not (self.user or "").strip():
            raise ValueError("lookup.atlassian requires user (or via connection_ref).")
        if self.api_token is None:
            raise ValueError("lookup.atlassian requires api_token (or via connection_ref).")
        secret = self.api_token.get_secret_value() if hasattr(self.api_token, "get_secret_value") else str(self.api_token)
        if not str(secret).strip():
            raise ValueError("lookup.atlassian requires api_token (or via connection_ref).")
        return self


class AtlassianLookupPlugin(BaseLookupPlugin):
    plugin_name = "atlassian"

    def __init__(self, **config: Any):
        cfg = AtlassianLookupPluginConfig(**config)
        super().__init__(default_team_ttl_seconds=cfg.default_team_ttl_seconds)
        self.cfg = cfg
        self._site_url = str(cfg.site_url).strip().rstrip("/")
        self._cloud_id = str(cfg.cloud_id).strip()
        self._org_id = str(cfg.org_id).strip()
        self._user = str(cfg.user).strip()
        tok = cfg.api_token
        token_str = tok.get_secret_value() if hasattr(tok, "get_secret_value") else str(tok)
        self._auth = HTTPBasicAuth(self._user, token_str)
        self._json_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _request_timeout(self) -> tuple[float, float]:
        return timeout_pair(float(self.cfg.http_timeout_seconds))

    def _log_debug_exchange(self, *, method: str, url: str, response: Optional[requests.Response] = None) -> None:
        if not self.logger.isEnabledFor(logging.DEBUG):
            return
        self.logger.debug("%s %s", method.upper(), url)
        if response is not None:
            try:
                body = response.json()
                self.logger.debug("response json: %s", json.dumps(body, default=str)[:65536])
            except Exception:
                txt = (response.text or "")[:65536]
                self.logger.debug("response text: %s", txt)

    def _iter_team_pages(self) -> Iterator[Tuple[List[Dict[str, Any]], Optional[str]]]:
        """Yield (entities_batch, cursor_for_next) until no cursor."""
        org = self._org_id
        site = self._cloud_id
        size = int(self.cfg.teams_page_size)
        url = f"{ATLASSIAN_API_BASE}/public/teams/v1/org/{org}/teams"
        cursor: Optional[str] = None
        while True:
            params: Dict[str, Any] = {"siteId": site, "size": size}
            if cursor:
                params["cursor"] = cursor
            try:
                r = requests.get(
                    url,
                    params=params,
                    headers=self._json_headers,
                    auth=self._auth,
                    timeout=self._request_timeout(),
                )
                self._log_debug_exchange(method="GET", url=r.url, response=r)
                r.raise_for_status()
                payload = r.json()
            except Exception as e:
                self.logger.error("Public Teams list request failed: %s", e)
                raise

            if not isinstance(payload, dict):
                self.logger.warning("Public Teams list returned non-object JSON; treating as empty.")
                yield [], None
                return

            entities = payload.get("entities")
            if entities is None:
                entities = []
            if not isinstance(entities, list):
                self.logger.warning("Public Teams list 'entities' is not a list; treating as empty.")
                entities = []

            if len(entities) == 0:
                self.logger.warning("Public Teams list returned an empty page (org=%s, siteId=%s).", org, site)

            next_cursor = payload.get("cursor")
            if isinstance(next_cursor, str):
                next_cursor = next_cursor.strip() or None
            else:
                next_cursor = None

            yield entities, next_cursor

            if not next_cursor:
                break
            cursor = next_cursor

    def preload_teams_cache(self) -> None:
        """Leader init: cache all org teams (name + Jira team id), no members."""
        stub_bot = SimpleNamespace(lookup_plugin=None, log=self.logger)
        total = 0
        for entities, _ in self._iter_team_pages():
            for item in entities:
                if not isinstance(item, dict):
                    self.logger.warning("Skipping non-object team entry: %s", item)
                    continue
                team_id = str(item.get("teamId") or "").strip()
                display = str(item.get("displayName") or "").strip()
                if not team_id or not display:
                    self.logger.warning("Skipping team with missing teamId or displayName: %s", item)
                    continue
                t = ThaumTeam(
                    bot=stub_bot,  # type: ignore[arg-type]
                    team_name=display,
                    alert_id=team_id,
                    lookup_id=team_id,
                    # Lazy member loading: force first real member lookup on use.
                    last_cached=0.0,
                    _members=[],
                )
                try:
                    self.cache_team(t, bot_plugin_name=_JIRA_PLATFORM_KEY, team_id=team_id)
                    total += 1
                except Exception as e:
                    self.logger.error("Failed to cache team %r (%s): %s", display, team_id, e)
        if total == 0:
            self.logger.warning("Atlassian team preload stored no teams (check org_id, siteId, and credentials).")
        else:
            self.logger.info("Atlassian team preload cached %s teams (members not loaded).", total)

    def _extract_account_ids_from_members_payload(self, payload: Dict[str, Any]) -> List[str]:
        ids: List[str] = []
        for key in ("results", "entities", "members", "accountIds"):
            raw = payload.get(key)
            if not isinstance(raw, list):
                continue
            for item in raw:
                if isinstance(item, str) and item.strip():
                    ids.append(item.strip())
                elif isinstance(item, dict):
                    aid = item.get("accountId") or item.get("id")
                    if isinstance(aid, str) and aid.strip():
                        ids.append(aid.strip())
        # de-dupe preserving order
        seen: set[str] = set()
        out: List[str] = []
        for i in ids:
            if i not in seen:
                seen.add(i)
                out.append(i)
        return out

    def _iter_member_account_ids(self, team_id: str) -> Iterator[str]:
        org = self._org_id
        site = self._cloud_id
        url = f"{ATLASSIAN_API_BASE}/public/teams/v1/org/{org}/teams/{team_id}/members"
        params = {"siteId": site}
        after: Optional[str] = None
        while True:
            if after is None:
                body: Dict[str, Any] = {}
            else:
                body = {"after": after, "first": 50}
            try:
                r = requests.post(
                    url,
                    params=params,
                    headers=self._json_headers,
                    auth=self._auth,
                    json=body,
                    timeout=self._request_timeout(),
                )
                self._log_debug_exchange(method="POST", url=r.url, response=r)
                r.raise_for_status()
                payload = r.json()
            except Exception as e:
                self.logger.error("Team members request failed for team_id=%s: %s", team_id, e)
                raise

            if not isinstance(payload, dict):
                self.logger.warning("Team members returned non-object JSON for team_id=%s.", team_id)
                return

            ids = self._extract_account_ids_from_members_payload(payload)
            if not ids:
                self.logger.warning("Team members returned no account ids for team_id=%s.", team_id)

            for aid in ids:
                yield aid

            page_info = payload.get("pageInfo")
            has_next = False
            end_cursor: Optional[str] = None
            if isinstance(page_info, dict):
                has_next = bool(page_info.get("hasNextPage"))
                ec = page_info.get("endCursor")
                if isinstance(ec, str) and ec.strip():
                    end_cursor = ec.strip()
            if not has_next or not end_cursor:
                break
            after = end_cursor

    def _fetch_jira_user(self, account_id: str) -> Optional[ThaumPerson]:
        url = f"{self._site_url}/rest/api/3/user"
        try:
            r = requests.get(
                url,
                params={"accountId": account_id},
                headers={"Accept": "application/json"},
                auth=self._auth,
                timeout=self._request_timeout(),
            )
            self._log_debug_exchange(method="GET", url=r.url, response=r)
            r.raise_for_status()
            u = r.json()
        except Exception as e:
            self.logger.error("Jira user lookup failed for accountId=%s: %s", account_id, e)
            return None

        if not isinstance(u, dict):
            return None
        email = str(u.get("emailAddress") or "").strip().lower()
        display = str(u.get("displayName") or "").strip()
        if not email:
            self.logger.warning("Jira user %s has no emailAddress; cannot merge into person cache by email.", account_id)
            return None

        return ThaumPerson(
            email=email,
            display_name=display,
            platform_ids={_JIRA_PLATFORM_KEY: account_id},
            source_plugin=self.plugin_name,
        )

    def _resolve_person_by_email_via_jira(self, email_key: str) -> Optional[ThaumPerson]:
        """Jira ``GET /rest/api/3/user/search`` by email; merge into cache when a match is found."""
        url = f"{self._site_url}/rest/api/3/user/search"
        try:
            response = requests.get(
                url,
                headers={"Accept": "application/json"},
                params={"query": email_key, "maxResults": 50},
                auth=self._auth,
                timeout=self._request_timeout(),
            )
            self._log_debug_exchange(method="GET", url=response.url, response=response)
            response.raise_for_status()
        except Exception as e:
            self.logger.warning("Jira user/search failed for %s: %s", email_key, e)
            return None

        users = response.json()
        if not isinstance(users, list):
            return None

        def _merge_from_entry(u: dict) -> Optional[ThaumPerson]:
            account_id = str((u.get("accountId") or "")).strip()
            if not account_id:
                return None
            display_name = str((u.get("displayName") or "")).strip()
            fragment = ThaumPerson(
                email=email_key,
                platform_ids={_JIRA_PLATFORM_KEY: account_id},
                source_plugin=self.plugin_name,
            )
            if display_name:
                fragment.display_name = display_name
            return self.merge_person(fragment)

        for u in users:
            if not isinstance(u, dict):
                continue
            email_addr = str((u.get("emailAddress") or "")).strip().lower()
            account_id = str((u.get("accountId") or "")).strip()
            if account_id and email_addr == email_key:
                return _merge_from_entry(u)

        for u in users:
            if not isinstance(u, dict):
                continue
            account_id = str((u.get("accountId") or "")).strip()
            if account_id:
                return _merge_from_entry(u)

        return None

    def get_person_by_email(self, email: str) -> Optional[ThaumPerson]:
        key = (email or "").strip().lower()
        if not key:
            return None
        cached = self._get_cached_person_by_email(key)
        if cached is not None and cached.platform_ids.get(_JIRA_PLATFORM_KEY):
            return cached
        resolved = self._resolve_person_by_email_via_jira(key)
        if resolved is not None:
            return resolved
        return cached

    def get_person_by_id(self, bot_plugin_name: str, person_id: str) -> Optional[ThaumPerson]:
        cached = super().get_person_by_id(bot_plugin_name, person_id)
        if cached is not None:
            return cached
        if bot_plugin_name != _JIRA_PLATFORM_KEY:
            return None
        frag = self._fetch_jira_user(person_id.strip())
        if frag is None:
            return None
        return self.merge_person(frag)

    def fetch_team_members(self, team: ThaumTeam) -> List[ThaumPerson]:
        team_id = (team.lookup_id or team.alert_id or "").strip()
        if not team_id:
            self.logger.warning("Atlassian fetch_team_members: missing team id on ThaumTeam.")
            return []

        people: List[ThaumPerson] = []
        try:
            for account_id in self._iter_member_account_ids(team_id):
                p = self._fetch_jira_user(account_id)
                if p is not None:
                    people.append(p)
        except Exception as e:
            self.logger.error("fetch_team_members failed for team_id=%s: %s", team_id, e)
            if self.logger.isEnabledFor(LogLevel.SPAM):
                import traceback

                self.logger.log(LogLevel.SPAM, "%s", traceback.format_exc())
            return []

        return people


def create_instance_lookup(config_raw: dict) -> AtlassianLookupPlugin:
    return AtlassianLookupPlugin(**(config_raw or {}))


def get_config_model():
    return AtlassianLookupPluginConfig


def maintenance_tasks_register(registry: Any, *, server_cfg: ServerConfig, config: Dict[str, Any]) -> None:
    return


def leader_init_tasks_register(registry: Any, *, server_cfg: ServerConfig, config: Dict[str, Any]) -> None:
    """Register Public Teams preload on the election leader before ``initialize_bots``."""

    def _preload(_server_cfg: ServerConfig, _config: Dict[str, Any]) -> None:
        from lookup.instance import get_lookup_plugin

        plugin = get_lookup_plugin()
        if not isinstance(plugin, AtlassianLookupPlugin):
            return
        plugin.preload_teams_cache()

    registry.register_init_task("atlassian_preload_teams", _preload)
