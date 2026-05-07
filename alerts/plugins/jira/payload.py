# SPDX-License-Identifier: MPL-2.0
# Copyright 2026 Clinton Bunch
# alerts/plugins/jira/payload.py
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, Optional

import requests

from thaum.http_timeouts import timeout_pair
from thaum.types import AlertPriority, RespondersList, ThaumPerson


def responders_list_to_jira_payload(
    responders: RespondersList,
    resolve_email_to_account_id: Callable[[str], Optional[str]],
    logger: logging.Logger,
) -> list[dict[str, str]]:
    """
    Convert typed responders into Jira alert responder dicts.

    Team -> {"type": "team", "id": "<teamId>"}
    Person -> {"type": "user", "id": "<accountId>"}
    """
    payload: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for team in responders.teams:
        tid = (team.alert_id or team.lookup_id or "").strip()
        if not tid:
            continue
        key = ("team", tid)
        if key in seen:
            continue
        seen.add(key)
        payload.append({"type": "team", "id": tid})

    for person in responders.people:
        account_id = (person.platform_ids.get("jira") or "").strip()
        if not account_id:
            account_id = resolve_email_to_account_id(person.email)
        if not account_id:
            logger.warning("Jira responder email '%s' did not resolve to accountId", person.email)
            continue
        key = ("user", account_id)
        if key in seen:
            continue
        seen.add(key)
        payload.append({"type": "user", "id": account_id})

    return payload
# -- End Function responders_list_to_jira_payload


def post_alert(
    url: str,
    alert: dict[str, Any],
    headers: dict[str, str],
    auth: Any,
    read_timeout: float = 15.0,
) -> requests.Response:
    return requests.post(
        url,
        data=json.dumps(alert),
        headers=headers,
        auth=auth,
        timeout=timeout_pair(read_timeout),
    )
# -- End Function post_alert


def parse_created_alert_id(response: requests.Response) -> str:
    jira_alert_id = ""
    try:
        resp_json = response.json()
        jira_alert_id = str(resp_json.get("alertId") or resp_json.get("id") or "")
    except (json.JSONDecodeError, AttributeError, TypeError, ValueError):
        jira_alert_id = ""
    return jira_alert_id
# -- End Function parse_created_alert_id


def build_sender_extra_properties(sender: ThaumPerson, plugin_name: str) -> tuple[str, str]:
    """
    Sender fields for Jira ``extraProperties`` (no email — privacy).

    ``name`` uses display name only; if absent, ``"Someone"`` (email is never sent).
    ``bot_person_id`` is returned for legacy callers.
    """
    display = (sender.display_name or "").strip() or "Someone"
    pid = (sender.platform_ids or {}).get(plugin_name, "") or ""
    return display, pid
# -- End Function build_sender_extra_properties


def build_trigger_alert_body(
    summary: str,
    bot_handle: str,
    room_id: str,
    sender: ThaumPerson,
    priority: AlertPriority,
    priority_normal: str,
    priority_high: str,
    short_id: str,
    responders_payload: list[dict[str, str]],
    bot_key: str,
    plugin_name: str,
) -> dict[str, Any]:
    severity = priority_high if priority == AlertPriority.HIGH else priority_normal
    sender_name, _sender_pid = build_sender_extra_properties(sender, plugin_name)
    alert: dict[str, Any] = {
        "message": summary,
        "source": bot_handle,
        "alias": f"THAUM-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{short_id}",
        "priority": severity,
        "responders": responders_payload,
        "extraProperties": {
            "sender": sender_name,
            "short_id": short_id,
        },
    }
    if priority == AlertPriority.HIGH:
        alert["tags"] = ["OverrideQuietHours", "HighPriority"]
    return alert
# -- End Function build_trigger_alert_body
