# SPDX-License-Identifier: MPL-2.0
# Copyright 2026 Clinton Bunch
# tests/test_responder_resolution.py
from __future__ import annotations

import logging
import unittest
from unittest.mock import MagicMock, patch

from pydantic import SecretStr

from alerts.plugins.jira.config import JiraAlertPluginConfig
from alerts.plugins.jira.payload import responders_list_to_jira_payload
from alerts.plugins.jira.plugin import JiraPlugin
from bots.base import BaseChatBotConfig
from connections.plugins.atlassian import AtlassianConnectionConfig
from lookup.base import BaseLookupPlugin
from thaum.db_bootstrap import init_app_db
from thaum.types import RespondersList, ThaumPerson, ThaumTeam, schema_only_validation


class _LookupTestPlugin(BaseLookupPlugin):
    plugin_name = "test_lookup"

    def fetch_team_members(self, team: ThaumTeam) -> list[ThaumPerson]:
        return list(team._members)


class ResponderResolutionTest(unittest.TestCase):
    def setUp(self) -> None:
        init_app_db("sqlite:///:memory:")
        self.lookup = _LookupTestPlugin()
        self.bot = MagicMock()
        self.bot.lookup_plugin = self.lookup
    # -- End Method setUp

    def test_resolve_responder_refs_supports_id_formats(self) -> None:
        self.lookup.cache_team(
            ThaumTeam(bot=self.bot, team_name="DBA", _members=[]),
            bot_plugin_name="jira",
            team_id="team-123",
        )

        responders = self.lookup.resolve_responder_refs(
            self.bot,
            ["id:team:team-123", "id:person:user-456"],
            source_plugin="jira_config",
        )

        self.assertEqual(len(responders.teams), 1)
        self.assertEqual(responders.teams[0].team_name, "DBA")
        self.assertEqual(responders.teams[0].alert_id, "team-123")
        self.assertEqual(len(responders.people), 1)
        self.assertEqual(responders.people[0].platform_ids.get("jira"), "user-456")
    # -- End Method test_resolve_responder_refs_supports_id_formats

    def test_resolve_responder_refs_supports_team_names_with_spaces(self) -> None:
        self.lookup.cache_team(
            ThaumTeam(bot=self.bot, team_name="DBA Team", _members=[]),
            bot_plugin_name="jira",
            team_id="team-space-1",
        )
        responders = self.lookup.resolve_responder_refs(self.bot, ["team:DBA Team"])
        self.assertEqual(len(responders.teams), 1)
        self.assertEqual(responders.teams[0].team_name, "DBA Team")
        self.assertEqual(responders.teams[0].alert_id, "team-space-1")
    # -- End Method test_resolve_responder_refs_supports_team_names_with_spaces

    def test_resolve_responder_refs_fuzzy_team_name_near_miss(self) -> None:
        """Typo/near-miss display names (e.g. DBA vs DBAs) resolve to the cached team row."""
        self.lookup.cache_team(
            ThaumTeam(bot=self.bot, team_name="Gemstone - DBAs", _members=[])
        )
        responders = self.lookup.resolve_responder_refs(
            self.bot, ["team:Gemstone - DBA"]
        )
        self.assertEqual(len(responders.teams), 1)
        self.assertEqual(responders.teams[0].team_name, "Gemstone - DBAs")
    # -- End Method test_resolve_responder_refs_fuzzy_team_name_near_miss


class JiraResponderSourceTest(unittest.TestCase):
    def _make_plugin(self, responders: list[str]) -> JiraPlugin:
        cfg = JiraAlertPluginConfig.model_construct(
            plugin="jira",
            site_url="https://example.atlassian.net",
            cloud_id="cloud-id",
            user="user@example.com",
            api_token=SecretStr("token"),
            responders=responders,
            status_webhook_bearer="",
            send_escalate_msg=False,
        )
        plugin = JiraPlugin(cfg)
        plugin._refresh_team_cache = lambda: None
        bot = MagicMock()
        bot.lookup_plugin = MagicMock()
        bot.responders = RespondersList(
            people=[ThaumPerson(email="bot@example.com")],
            teams=[ThaumTeam(bot=bot, team_name="BotTeam", alert_id="team-bot")],
        )
        plugin.attach_bot(bot)
        return plugin

    def test_jira_config_responders_are_authoritative(self) -> None:
        plugin = self._make_plugin(["id:person:user-111"])
        plugin.bot.lookup_plugin.resolve_responder_refs.return_value = RespondersList(
            people=[ThaumPerson(email="jira-account-id:user-111", platform_ids={"jira": "user-111"})],
            teams=[],
        )

        responders = plugin._resolve_alert_responders()

        self.assertEqual(len(responders.people), 1)
        self.assertEqual(responders.people[0].platform_ids.get("jira"), "user-111")
        self.assertTrue(plugin.bot.lookup_plugin.resolve_responder_refs.called)
    # -- End Method test_jira_config_responders_are_authoritative

    def test_empty_jira_responders_fall_back_to_bot_responders(self) -> None:
        plugin = self._make_plugin([])

        responders = plugin._resolve_alert_responders()

        self.assertEqual(len(responders.people), 1)
        self.assertEqual(responders.people[0].email, "bot@example.com")
        self.assertEqual(len(responders.teams), 1)
        self.assertEqual(responders.teams[0].team_name, "BotTeam")
    # -- End Method test_empty_jira_responders_fall_back_to_bot_responders


class JiraResponderPayloadTest(unittest.TestCase):
    def test_payload_prefers_jira_platform_id_for_person(self) -> None:
        responders = RespondersList(
            people=[ThaumPerson(email="placeholder@example.com", platform_ids={"jira": "acct-42"})],
            teams=[],
        )
        resolver = MagicMock(return_value=None)

        payload = responders_list_to_jira_payload(responders, resolver, logging.getLogger("test.jira.payload"))

        self.assertEqual(payload, [{"type": "user", "id": "acct-42"}])
        resolver.assert_not_called()
    # -- End Method test_payload_prefers_jira_platform_id_for_person


class SensitiveConfigSecretResolutionTest(unittest.TestCase):
    def test_atlassian_sensitive_fields_resolve(self) -> None:
        def _fake_resolve_secret(value: str) -> str:
            return f"resolved:{value}"

        with patch("thaum.types.resolve_secret", side_effect=_fake_resolve_secret):
            cfg = AtlassianConnectionConfig(
                plugin="atlassian",
                site_url="secret:site-url",
                cloud_id="secret:cloud-id",
                org_id="secret:org-id",
                user="secret:login-email",
                api_token="secret:api-token",
            )

        self.assertEqual(cfg.site_url, "resolved:secret:site-url")
        self.assertEqual(cfg.cloud_id, "resolved:secret:cloud-id")
        self.assertEqual(cfg.org_id, "resolved:secret:org-id")
        self.assertEqual(cfg.user, "resolved:secret:login-email")
        self.assertEqual(cfg.api_token, "resolved:secret:api-token")

    def test_responder_entries_resolve_for_bot_and_jira(self) -> None:
        def _fake_resolve_secret(value: str) -> str:
            return f"resolved:{value}"

        with patch("thaum.types.resolve_secret", side_effect=_fake_resolve_secret):
            bot_cfg = BaseChatBotConfig(
                handle="test",
                endpoint="https://thaum.example.invalid/bot/test",
                send_alerts=False,
                high_pri_on=False,
                alert_type="null",
                responders=["secret:team-ref", "secret:person-ref"],
                team_description="Test Team",
                emergency_warning_message="",
            )
            jira_cfg = JiraAlertPluginConfig(
                plugin="jira",
                site_url="secret:site-url",
                cloud_id="secret:cloud-id",
                user="secret:login-email",
                api_token=SecretStr("token"),
                responders=["secret:team-ref", "secret:person-ref"],
                status_webhook_bearer="",
                send_escalate_msg=False,
            )

        self.assertEqual(bot_cfg.responders, ["resolved:secret:team-ref", "resolved:secret:person-ref"])
        self.assertEqual(jira_cfg.responders, ["resolved:secret:team-ref", "resolved:secret:person-ref"])

    def test_schema_only_mode_keeps_sensitive_refs_unresolved(self) -> None:
        with patch("thaum.types.resolve_secret") as mock_resolve:
            with schema_only_validation():
                cfg = JiraAlertPluginConfig(
                    plugin="jira",
                    site_url="secret:site-url",
                    cloud_id="secret:cloud-id",
                    user="secret:login-email",
                    api_token="secret:api-token",
                    responders=["secret:team-ref", "secret:person-ref"],
                    status_webhook_bearer="",
                    send_escalate_msg=False,
                )
        mock_resolve.assert_not_called()
        self.assertEqual(cfg.site_url, "secret:site-url")
        self.assertEqual(cfg.cloud_id, "secret:cloud-id")
        self.assertEqual(cfg.user, "secret:login-email")
        self.assertEqual(cfg.responders, ["secret:team-ref", "secret:person-ref"])
        self.assertEqual(cfg.api_token.get_secret_value(), "secret:api-token")


if __name__ == "__main__":
    unittest.main()
