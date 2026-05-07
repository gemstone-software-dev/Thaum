# SPDX-License-Identifier: MPL-2.0
# Copyright 2026 Clinton Bunch
# alerts/plugins/jira/config.py
from __future__ import annotations

from typing import Optional

from pydantic import ConfigDict, Field

from alerts.base import BaseAlertPluginConfig
from thaum.types import OptionalResolvedSecret, ResolvedSecret, ResolvedStringList

_DEFAULT_STATUS_ACK = (
    "{{ responder_mention }} has acknowledged the alert and should be joining you shortly. "
    "Allow time to login."
)
_DEFAULT_STATUS_UNACK = (
    "{{ responder_mention }} is not able to help you after all, escalating to next level. "
    "Thank you for your patience."
)
_DEFAULT_STATUS_ESCALATE = "The alert has been escalated, thank you for your patience."


class JiraAlertPluginConfig(BaseAlertPluginConfig):
    """Status Jinja templates get: team_description, sender_*, responder_* (see status_webhook)."""

    plugin: str = "jira"
    connection_ref: Optional[str] = Field(
        default=None,
        description=(
            "Optional name under [connections.*]; merged at bootstrap via "
            "connections.merge.merge_connection_profile (same as lookup). "
            "Requires site_url, cloud_id, user, and api_token after merge."
        ),
    )
    site_url: OptionalResolvedSecret
    cloud_id: OptionalResolvedSecret
    user: OptionalResolvedSecret
    api_token: ResolvedSecret
    responders: ResolvedStringList
    priority_normal: str = "P3"
    priority_high: str = "P2"
    status_webhook_bearer: str
    send_escalate_msg: bool = False
    status_ack_template: str = Field(default=_DEFAULT_STATUS_ACK)
    status_unack_template: str = Field(default=_DEFAULT_STATUS_UNACK)
    status_escalate_template: str = Field(default=_DEFAULT_STATUS_ESCALATE)

    model_config = ConfigDict(extra="allow")
# -- End Class JiraAlertPluginConfig
