# SPDX-License-Identifier: MPL-2.0
# Copyright 2026 Clinton Bunch
# thaum/handlers.py
import json
import logging
from pathlib import Path
from jinja2 import Environment, StrictUndefined, Template
from thaum.engine import create_incident_room, acknowledge_incident
from typing import TYPE_CHECKING, Any, Dict
from thaum.types import ThaumPerson, AlertPriority
import re

if TYPE_CHECKING:
    from bots.base import BaseChatBot, MessageContext


_log = logging.getLogger(__name__)
_jinja_env = Environment(undefined=StrictUndefined)

DEFAULT_INCIDENT_PROMPT_CARD_TEMPLATE = """
{
  "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
  "type": "AdaptiveCard",
  "version": "1.3",
  "body": [
    {
      "type": "TextBlock",
      "text": {{ ("How can " ~ team_description ~ " help you today?") | tojson }},
      "wrap": true
    },
    {
      "type": "Input.Text",
      "id": "summary",
      "label": "Summary",
      "placeholder": "Briefly describe what you need (if spaces fail in Webex, use +)",
      "isMultiline": true,
      "isRequired": true
    }
    {% if show_priority_toggle %},
    {
      "type": "Input.Toggle",
      "id": "is_emergency",
      "title": "High priority (emergency) alert",
      "value": {{ ("true" if default_high_priority else "false") | tojson }},
      "valueOn": "true",
      "valueOff": "false"
    }
    {% endif %}
  ],
  "actions": [
    {
      "type": "Action.Submit",
      "title": "Submit",
      "data": {
        "action": "submit_incident"
        {% if not show_priority_toggle %},
        "is_emergency": "false"
        {% endif %}
      }
    }
  ]
}
"""

def _is_valid_incident_card(card: Any) -> bool:
    if not isinstance(card, dict):
        return False
    if card.get("type") != "AdaptiveCard":
        return False
    if not isinstance(card.get("version"), str):
        return False
    if not isinstance(card.get("body"), list):
        return False
    if not isinstance(card.get("actions"), list):
        return False
    return True


def _incident_prompt_card(
    bot: "BaseChatBot",
    team_description: str,
    default_high_priority: bool,
    show_priority_toggle: bool,
) -> Dict[str, Any]:
    inline_template = (getattr(bot, "incident_prompt_card_template", None) or "").strip()
    template_path = (getattr(bot, "incident_prompt_card_template_path", None) or "").strip()
    context = {
        "team_description": team_description,
        "default_high_priority": default_high_priority,
        "show_priority_toggle": show_priority_toggle,
    }

    def _render_card(source: str) -> Dict[str, Any]:
        rendered = _jinja_env.from_string(source).render(**context)
        parsed = json.loads(rendered)
        if _is_valid_incident_card(parsed):
            return parsed
        raise ValueError("Rendered incident prompt card is not a valid Adaptive Card object")

    try:
        if inline_template:
            source = inline_template
        elif template_path:
            source = Path(template_path).read_text(encoding="utf-8")
        else:
            source = DEFAULT_INCIDENT_PROMPT_CARD_TEMPLATE
        return _render_card(source)
    except Exception as exc:
        _log.warning("Using default incident prompt card due to template error: %s", exc)
        return _render_card(DEFAULT_INCIDENT_PROMPT_CARD_TEMPLATE)




# Alert command: usage documents ``on-call``; ``alert``, ``oncall``, and ``on_call`` are synonyms.
# ``alert!`` is high priority (``alert!`` before ``alert`` so the exclamation form matches first).
ALERT_COMMAND_PATTERN = r"^(?P<cmd>alert!|alert|on[-_]?call)(?:\s*:\s*(?P<msg>.*))?$"


# Define the template globally (or in a separate file if it gets too long)
USAGE_TEMPLATE = """
help[: summary]
  Creates a new room and adds you and {{ bot.team_description }}
  {%- if bot.send_alerts %} and alerts the on-call person.{% endif %}
  If summary is not provided, you will be prompted. The summary is echoed in the new room
  {%- if bot.send_alerts %} and included in the alert.{% endif %}
{% if bot.high_pri_on %}
emergency[: summary]
  Just like help, but sends a higher priority alert. {{ bot.emergency_warning_message }}
alert![: message]
  Like alert, but sends a higher priority on-call alert. Does not create a room.
{% endif %}
{% if bot.send_alerts %}
alert[: message]
on-call[: message]
  Alerts the {{ bot.team_description }} on-call with a message. Does not create a room.
{%- if supports_acknowledge %}
  Produces an alert ID for tracking.
ack alert_id
  Acknowledges an alert and assigns ownership to you.
{%- endif %}
{% endif %}
implode
  Deletes the current room if {{ bot.handle }} created it.
usage|commands|?
  Prints this message.
"""



def bind_thaum_handlers(bot: 'BaseChatBot') -> None:
    """Connects Bot events to Engine business logic."""
    
    # Handles the Help or conditionally the emergency command
    def handle_help_emergency(bot: 'BaseChatBot', message: 'MessageContext', match: re.Match):
        cmd = match.group("cmd").lower()
        raw = match.group("summary")
        summary = (raw or "").strip()
        priority = AlertPriority.HIGH if cmd == "emergency" else AlertPriority.NORMAL
        if summary:
            create_incident_room(bot, summary, message.person, priority)
        else:
            card = _incident_prompt_card(
                bot,
                bot.team_description,
                default_high_priority=(cmd == "emergency"),
                show_priority_toggle=bool(bot.high_pri_on),
            )
            bot.send_card(
                message.room_id,
                card,
                fallback_text="Incident request — please fill in the card.",
            )
    # -- End Function handle_help_emergency

    # register both commands to the same handler
    bot.hears(r"^(?P<cmd>help)(?:\s*:\s*(?P<summary>.*))?$",priority=10)(handle_help_emergency)
    
    if bot.high_pri_on:
        bot.hears(r"^(?P<cmd>emergency)(?:\s*:\s*(?P<summary>.*))?$",priority=10)(handle_help_emergency)

    # conditionally register the alert command; ack only when the plugin supports chat ack
    if bot.send_alerts:
        plugin_cls = type(bot.alert_plugin)

        @bot.hears(ALERT_COMMAND_PATTERN, priority=10)
        def handle_alert(bot: 'BaseChatBot', ctx: 'MessageContext', match: re.Match):
            cmd = (match.group("cmd") or "").lower()
            if cmd == "alert!" and not bot.high_pri_on:
                bot.say(
                    ctx.room_id,
                    "High priority `alert!` is not enabled for this bot. Use `alert` instead.",
                )
                return
            priority = AlertPriority.HIGH if cmd == "alert!" else AlertPriority.NORMAL
            msg = (match.group("msg") or "").strip()
            title = bot.room_title(ctx.room_id)
            if msg:
                alert_msg = f"{ctx.person.for_display} needs you in {title}: {msg}"
            else:
                alert_msg = f"{ctx.person.for_display} needs you in {title}"
            short_id, _alert_id = bot.alert_plugin.trigger_alert(
                alert_msg, ctx.room_id, ctx.person, priority
            )
            if short_id:
                bot.say(
                    ctx.room_id,
                    f"Alert sent. Tracking ID: **{short_id}**",
                )
            else:
                bot.say(ctx.room_id, "Alert sent.")

        if plugin_cls.supports_acknowledge:

            @bot.hears(r"^ack\s+(?P<alert_id>[A-Z2-9]{4}).*$", priority=10)
            def handle_ack(bot: 'BaseChatBot', ctx: 'MessageContext', match: re.Match):
                acknowledge_incident(bot, match.group("alert_id"), ctx.person)
    # -- End if send_alerts
    
    @bot.hears(r"^\s*(implode).*$", priority=80)
    def handle_implode(bot: 'BaseChatBot', ctx: 'MessageContext', match: re.Match):
        bot.delete_room(ctx.room_id,ctx.person)
    
    @bot.hears(r"^\s*(usage|commands|\?).*",priority=90)
    def handle_usage(bot, ctx, match):
        supports_acknowledge = type(bot.alert_plugin).supports_acknowledge
        rendered = Template(USAGE_TEMPLATE).render(bot=bot, supports_acknowledge=supports_acknowledge)
        bot.say(ctx.room_id, rendered)
    
    @bot.hears(r"^(?P<cmd>\S+)\s+.*$",priority=99)
    def handle_unknown(bot: 'BaseChatBot', ctx: 'MessageContext', match: re.Match):
        bot.say(ctx.room_id,f"Unknown command {match.group('cmd')}. Please use @{bot.handle} usage to see a list of commands")

    
    @bot.on_action
    def handle_actions(bot, action):
        """Processes Adaptive Card submissions (e.g. incident prompt from help/emergency)."""
        # 1. Input Validation — merged submit data uses string "action" (see _incident_prompt_card).
        action_type = action.inputs.get("action")
        if action_type != "submit_incident":
            return

        # 2. Extract inputs: summary from Input.Text; is_emergency from Toggle or submit data ("true"/"false").
        summary = action.inputs.get("summary", "No summary provided")
        if " " not in summary and "+" in summary:
            normalized_summary = summary.replace("+", " ")
            summary = normalized_summary
        is_emergency = action.inputs.get("is_emergency") == "true"
        priority = AlertPriority.HIGH if is_emergency else AlertPriority.NORMAL
        
        # 3. Resolve Identity via Driver-HAL
        # This keeps the Engine purely based on ThaumPerson objects
        speaker = bot.get_person(action.personId)
        
        # 4. Engine Call
        create_incident_room(bot, summary, speaker, priority)

        mid = getattr(action, "messageId", None) or getattr(action, "message_id", None)
        if mid:
            bot.delete_message(mid)
    # -- End Function handle_actions
# -- End Function bind_thaum_handlers
