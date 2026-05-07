# SPDX-License-Identifier: MPL-2.0
# Copyright 2026 Clinton Bunch
# tests/test_handlers_usage_ack.py
"""Tests for usage text and supports_acknowledge in thaum.handlers."""
import unittest
import re
from types import SimpleNamespace
from unittest.mock import MagicMock

from jinja2 import Template

from thaum.handlers import ALERT_COMMAND_PATTERN, USAGE_TEMPLATE, bind_thaum_handlers
from thaum.types import AlertPriority, ThaumPerson


class _StubAlertPlugin:
    supports_acknowledge = True


class _StubAlertPluginNoAck:
    supports_acknowledge = False


class _AlertPluginWithId:
    supports_acknowledge = False

    def trigger_alert(self, _msg, _room_id, _person, _priority=None):
        return ("ZXCV", "jira-id")


class _AlertPluginNoId:
    supports_acknowledge = True

    def trigger_alert(self, _msg, _room_id, _person, _priority=None):
        return ("", None)


class UsageTemplateAckTest(unittest.TestCase):
    def test_usage_includes_ack_when_supports_acknowledge(self) -> None:
        bot = MagicMock()
        bot.send_alerts = True
        bot.team_description = "SRE"
        bot.high_pri_on = False
        bot.handle = "ThaumBot"
        bot.emergency_warning_message = ""
        rendered = Template(USAGE_TEMPLATE).render(bot=bot, supports_acknowledge=True)
        self.assertIn("ack alert_id", rendered)
        self.assertIn("Produces an alert ID for tracking", rendered)
        self.assertIn("on-call[: message]", rendered)
        self.assertNotIn("alert![: message]", rendered)

    def test_usage_includes_alert_bang_when_high_priority_enabled(self) -> None:
        bot = MagicMock()
        bot.send_alerts = True
        bot.team_description = "SRE"
        bot.high_pri_on = True
        bot.handle = "ThaumBot"
        bot.emergency_warning_message = ""
        rendered = Template(USAGE_TEMPLATE).render(bot=bot, supports_acknowledge=False)
        self.assertIn("alert![: message]", rendered)
        self.assertIn("emergency[: summary]", rendered)

    def test_usage_omits_ack_when_not_supported(self) -> None:
        bot = MagicMock()
        bot.send_alerts = True
        bot.team_description = "SRE"
        bot.high_pri_on = False
        bot.handle = "ThaumBot"
        bot.emergency_warning_message = ""
        rendered = Template(USAGE_TEMPLATE).render(bot=bot, supports_acknowledge=False)
        self.assertNotIn("ack alert_id", rendered)
        self.assertNotIn("Produces an alert ID for tracking", rendered)
        self.assertIn("on-call[: message]", rendered)


class BindHandlersAckTest(unittest.TestCase):
    def test_ack_handler_registered_only_when_supported(self) -> None:
        bot = MagicMock()
        bot.send_alerts = True
        bot.high_pri_on = False
        bot.alert_plugin = _StubAlertPlugin()
        bot.hears = MagicMock(return_value=lambda f: f)

        bind_thaum_handlers(bot)

        patterns = [c[0][0] for c in bot.hears.call_args_list]
        ack_patterns = [p for p in patterns if "ack" in p and "alert_id" in p]
        self.assertEqual(len(ack_patterns), 1)

    def test_ack_handler_not_registered_when_unsupported(self) -> None:
        bot = MagicMock()
        bot.send_alerts = True
        bot.high_pri_on = False
        bot.alert_plugin = _StubAlertPluginNoAck()
        bot.hears = MagicMock(return_value=lambda f: f)

        bind_thaum_handlers(bot)

        patterns = [c[0][0] for c in bot.hears.call_args_list]
        ack_patterns = [p for p in patterns if "ack" in p and "alert_id" in p]
        self.assertEqual(len(ack_patterns), 0)


class AlertCommandShortIdOutputTest(unittest.TestCase):
    @staticmethod
    def _person() -> ThaumPerson:
        return ThaumPerson(email="x@example.com", display_name="X Person")

    @staticmethod
    def _build_bot(alert_plugin):
        trigger = MagicMock(side_effect=alert_plugin.trigger_alert)
        alert_plugin.trigger_alert = trigger
        routes = []

        def _hears(pattern, priority=50):
            compiled = re.compile(pattern)

            def _decorator(fn):
                routes.append((compiled, fn))
                return fn

            return _decorator

        return SimpleNamespace(
            send_alerts=True,
            high_pri_on=False,
            alert_plugin=alert_plugin,
            hears=_hears,
            on_action=lambda fn: fn,
            say=MagicMock(),
            delete_room=MagicMock(),
            team_description="SRE",
            handle="ThaumBot",
            emergency_warning_message="",
            send_card=MagicMock(),
            get_person=MagicMock(),
            delete_message=MagicMock(),
            room_title=MagicMock(return_value="Room A"),
        ), routes

    def test_alert_command_shows_tracking_id_when_present_even_without_ack_support(self) -> None:
        bot, routes = self._build_bot(_AlertPluginWithId())
        bind_thaum_handlers(bot)
        alert_pat = re.compile(ALERT_COMMAND_PATTERN)
        alert_handler = next(fn for pattern, fn in routes if pattern.pattern == alert_pat.pattern)
        ctx = SimpleNamespace(room_id="room-1", person=self._person())
        match = alert_pat.search("alert: test issue")
        self.assertIsNotNone(match)
        alert_handler(bot, ctx, match)
        bot.alert_plugin.trigger_alert.assert_called_once_with(
            "X Person needs you in Room A: test issue",
            "room-1",
            ctx.person,
            AlertPriority.NORMAL,
        )
        bot.say.assert_called_once_with("room-1", "Alert sent. Tracking ID: **ZXCV**")

    def test_alert_command_falls_back_when_no_short_id(self) -> None:
        bot, routes = self._build_bot(_AlertPluginNoId())
        bind_thaum_handlers(bot)
        alert_pat = re.compile(ALERT_COMMAND_PATTERN)
        alert_handler = next(fn for pattern, fn in routes if pattern.pattern == alert_pat.pattern)
        ctx = SimpleNamespace(room_id="room-2", person=self._person())
        match = alert_pat.search("alert: test issue")
        self.assertIsNotNone(match)
        alert_handler(bot, ctx, match)
        bot.alert_plugin.trigger_alert.assert_called_once_with(
            "X Person needs you in Room A: test issue",
            "room-2",
            ctx.person,
            AlertPriority.NORMAL,
        )
        bot.say.assert_called_once_with("room-2", "Alert sent.")

    def test_on_call_synonyms_invoke_same_handler(self) -> None:
        alert_pat = re.compile(ALERT_COMMAND_PATTERN)
        for line in ("on-call: ping", "oncall: ping", "on_call: ping"):
            with self.subTest(line=line):
                bot, routes = self._build_bot(_AlertPluginWithId())
                bind_thaum_handlers(bot)
                alert_handler = next(
                    fn for pattern, fn in routes if pattern.pattern == alert_pat.pattern
                )
                ctx = SimpleNamespace(room_id="room-x", person=self._person())
                match = alert_pat.search(line)
                self.assertIsNotNone(match, msg=f"pattern should match {line!r}")
                alert_handler(bot, ctx, match)
                bot.alert_plugin.trigger_alert.assert_called_once_with(
                    "X Person needs you in Room A: ping",
                    "room-x",
                    ctx.person,
                    AlertPriority.NORMAL,
                )

    def test_alert_bang_pattern_matches_and_on_call_bang_does_not(self) -> None:
        alert_pat = re.compile(ALERT_COMMAND_PATTERN)
        self.assertIsNotNone(alert_pat.match("alert!: urgent"))
        self.assertIsNotNone(alert_pat.match("alert!"))
        self.assertIsNone(alert_pat.match("on-call!: ping"))
        self.assertIsNone(alert_pat.match("oncall!: ping"))

    def test_alert_bang_uses_high_priority_when_enabled(self) -> None:
        bot, routes = self._build_bot(_AlertPluginWithId())
        bot.high_pri_on = True
        bind_thaum_handlers(bot)
        alert_pat = re.compile(ALERT_COMMAND_PATTERN)
        alert_handler = next(fn for pattern, fn in routes if pattern.pattern == alert_pat.pattern)
        ctx = SimpleNamespace(room_id="room-hi", person=self._person())
        match = alert_pat.search("alert!: production down")
        self.assertIsNotNone(match)
        alert_handler(bot, ctx, match)
        bot.alert_plugin.trigger_alert.assert_called_once_with(
            "X Person needs you in Room A: production down",
            "room-hi",
            ctx.person,
            AlertPriority.HIGH,
        )

    def test_alert_bang_rejected_when_high_priority_disabled(self) -> None:
        bot, routes = self._build_bot(_AlertPluginWithId())
        bot.high_pri_on = False
        bind_thaum_handlers(bot)
        alert_pat = re.compile(ALERT_COMMAND_PATTERN)
        alert_handler = next(fn for pattern, fn in routes if pattern.pattern == alert_pat.pattern)
        ctx = SimpleNamespace(room_id="room-no", person=self._person())
        match = alert_pat.search("alert!: nope")
        self.assertIsNotNone(match)
        alert_handler(bot, ctx, match)
        bot.alert_plugin.trigger_alert.assert_not_called()
        bot.say.assert_called_once()
        self.assertIn("not enabled", bot.say.call_args[0][1].lower())


if __name__ == "__main__":
    unittest.main()
