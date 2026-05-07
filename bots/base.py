# SPDX-License-Identifier: MPL-2.0
# Copyright 2026 Clinton Bunch
# bots/base.py
from __future__ import annotations
from abc import ABC, abstractmethod
import logging
from typing import List, Optional, Tuple, Callable, Dict, Any, Protocol, TYPE_CHECKING, Union
from thaum.types import ThaumPerson, RespondersList, ResolvedStringList
from dataclasses import dataclass, field
from pydantic import BaseModel, model_validator
import re

if TYPE_CHECKING:
    from flask import Request as FlaskRequest

@dataclass
class MessageContext:
    """The canonical object passed to every hears() handler."""
    room_id: str
    person: ThaumPerson
    message: str
    message_id: str
    raw_event: Dict[str,Any] = field(default_factory=dict)

class BotHearsHandler(Protocol):
    """ Signature for handlers for the hears decorator"""
    def __call__(self, bot: 'BaseChatBot', ctx: MessageContext, match: re.Match) -> None: ...

class BaseChatBot(ABC):
    """
    The Base Contract for all Thaum Bot drivers.
    Any platform-specific driver (Webex, Teams, Slack) must implement these methods.
    """
    
    plugin_name: str = 'base'

    def __init__(self, config: 'BaseChatBotConfig'):
        self.handle = config.handle
        self.logger = logging.getLogger(f"bot.{self.handle}")
        # Some identity/team flows expect a `.log` attribute for warnings.
        self.log = self.logger
        self.send_alerts = config.send_alerts
        self.high_pri_on = config.high_pri_on
        self.alert_type = config.alert_type
        self.responder_refs = list(config.responders)
        self.responders = RespondersList()
        self.team_description = config.team_description
        self.room_title_template = config.room_title_template
        self.customer_service_message_template = config.customer_service_message_template
        self.incident_prompt_card_template = config.incident_prompt_card_template
        self.incident_prompt_card_template_path = config.incident_prompt_card_template_path
        self.emergency_warning_message = config.emergency_warning_message
        # Set by the server bootstrap code; shared by all bots on a server.
        self.lookup_plugin: Optional[Any] = None
        # Configured in thaum.factory.initialize_bots: TOML bot id for /bot/<bot_key> routing.
        self.bot_key: Optional[str] = None
        self.endpoint = config.endpoint
        # Initialize state here
        self._hears_routes: List[Tuple[int, re.Pattern, Callable]] = []
        self._action_callbacks: List[Callable] = []
    # -- End Method __init__

    @abstractmethod
    def say(self, room_id: str, text: str, markdown: Optional[str] = None) -> None:
        """Sends a message to the specified room."""
        pass
    # -- End Method say

    @abstractmethod
    def send_card(self, room_id: str, card_content: dict, fallback_text: str) -> None:
        """Sends an Adaptive Card to the room."""
        pass
    # -- End Method send_card

    @abstractmethod
    def create_room(self, title: str) -> str:
        """Creates a room and returns the room_id."""
        pass
    # -- End Method create_room

    def room_title(self, room_id: str) -> str:
        """Returns a room's title for display; falls back to room_id."""
        return room_id
    # -- End Method room_title

    @abstractmethod
    def add_members(self, room_id: str, members: List[ThaumPerson]) -> None:
        """Adds a list of ThaumPeople to the room."""
        pass
    # -- End Method add_members

    @abstractmethod
    def delete_room(self, room_id: str, person: ThaumPerson) -> None:
        """Permanently removes/implodes the room."""
        pass
    # -- End Method delete_room

    def delete_message(self, message_id: str) -> None:
        """Remove a chat message by platform id (e.g. delete an Adaptive Card message). Default no-op."""
        return
    # -- End Method delete_message

    @abstractmethod
    def get_person(self, person_id: str) -> ThaumPerson:
        """Takes a bot_type-specific person_id and returns a ThaumPerson"""
        pass
    # -- End Method get_person

    def format_mention(self, person_or_id: Union[ThaumPerson, str, None]) -> str:
        """
        Platform mention token for use in markdown messages, or plain text when unsupported.
        Accepts a ``ThaumPerson`` or a native chat ``person_id`` string for this bot's
        ``plugin_name``.
        """
        if person_or_id is None:
            return ""
        if isinstance(person_or_id, ThaumPerson):
            pid = person_or_id.platform_ids.get(self.plugin_name)
            if pid:
                return self._mention_markdown_for_person_id(pid)
            return person_or_id.for_display
        s = str(person_or_id).strip()
        if not s:
            return ""
        return self._mention_markdown_for_person_id(s)
    # -- End Method format_mention

    def _mention_markdown_for_person_id(self, person_id: str) -> str:
        """Override in drivers that support @-mentions in ``say(..., markdown=True)``."""
        return person_id
    # -- End Method _mention_markdown_for_person_id

    @abstractmethod
    def handle_event(self, event: Dict[str, Any]) -> None:
        """Called by the bot's webhook route"""
        pass
    # -- End Method handle_event

    @abstractmethod
    def authenticate_request(self, request: "FlaskRequest") -> bool:
        """
        Verify the incoming request before calling `handle_event`.

        Subclasses should extract any required auth material from the request
        (e.g. headers, raw body) and return True on success.
        """
        pass
    # -- End Method authenticate_request

    @abstractmethod
    def register_bot_webhook(self) -> None:
        """
        Register inbound webhooks with the chat platform after HTTP routes are live
        (e.g. ``POST .../bot/<bot_key>``). Default no-op; Webex uses the leader maintenance loop.
        """
        return
    # -- End Method register_bot_webhook

    def hears(self, pattern: str, priority: int=50):
        """Decorator to register a regex pattern to a handler."""
        def decorator(handler: BotHearsHandler):
            self._hears_routes.append((priority,re.compile(pattern, re.IGNORECASE), handler))
            self._hears_routes.sort(key=lambda x: x[0])
            return handler
        return decorator

    def on_action(self, handler):
        """Decorator to register a callback for card actions."""
        self._action_callbacks.append(handler)
        return handler
# -- End Class BaseChatBot

class BaseChatBotConfig(BaseModel):
    """Web-style **mention** identifier for this bot (e.g. Webex Bot username), not logging or display."""

    handle: str
    # Public HTTPS URL for this bot's events (factory default: ``{base_url}/bot/{bot_key}``).
    endpoint: str
    high_pri_on: Optional[bool] = True
    send_alerts: Optional[bool] = True
    responders: ResolvedStringList
    room_title_template: Optional[str] = '{{requester_name}} - {{team_description}} {{date}}'
    customer_service_message_template: Optional[str] = (
        "Thank you for your patience.  The next available person from "
        "{{ team_description }} will be with you shortlly."
    )
    incident_prompt_card_template: Optional[str] = None
    incident_prompt_card_template_path: Optional[str] = None
    # Alert plugin module name under ``alerts.plugins``; use ``null`` when send_alerts is False.
    alert_type: str = "null"
    team_description: str
    emergency_warning_message: Optional[str]

    @model_validator(mode='after')
    def consistent_alert_settings(self) -> "BaseChatBotConfig":
        if self.send_alerts and self.alert_type == "null":
            raise ValueError(
                f"{self.handle}: send_alerts=True requires alert_type other than 'null'."
            )

        if not self.send_alerts and self.alert_type != "null":
            raise ValueError(
                f"{self.handle}: send_alerts=False requires alert_type='null'."
            )

        if self.high_pri_on:
            if not self.send_alerts:
                raise ValueError(
                    f"{self.handle}: high_pri_on=True requires send_alerts to also be True."
                )

        return self
    # -- End consistent_alert_settings
