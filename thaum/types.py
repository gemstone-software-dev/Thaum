# SPDX-License-Identifier: MPL-2.0
# Copyright 2026 Clinton Bunch
# thaum/types.py
import time
import os
from contextlib import contextmanager
from contextvars import ContextVar
from pydantic import ConfigDict, Field, model_validator, BaseModel, SecretStr, BeforeValidator
from typing import Any, Iterator, Optional, Annotated, Dict, List, TYPE_CHECKING
from enum import StrEnum,IntEnum,auto
from gemstone_utils.experimental.secrets_resolver import resolve_secret
import logging
from dataclasses import dataclass, field

if TYPE_CHECKING:
    from bots.base import BaseChatBot

# When True, ResolvedSecret / OptionalResolvedSecret keep raw reference strings (no env/file/azexp I/O).
config_schema_only: ContextVar[bool] = ContextVar("config_schema_only", default=False)


@contextmanager
def schema_only_validation() -> Iterator[None]:
    """Enable schema-only config validation (no secret resolution) for this block."""
    token = config_schema_only.set(True)
    try:
        yield
    finally:
        config_schema_only.reset(token)


def _resolved_secret_before(v: object) -> Any:
    if config_schema_only.get():
        return SecretStr(str(v))
    return resolve_secret(str(v))


def _optional_resolved_secret(v: object) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    if config_schema_only.get():
        return s
    return str(resolve_secret(s))


ResolvedSecret = Annotated[SecretStr, BeforeValidator(_resolved_secret_before)]
OptionalResolvedSecret = Annotated[Optional[str], BeforeValidator(_optional_resolved_secret)]

logger = logging.getLogger("thaum.types")

BaseUrlSource = StrEnum(
    "BaseUrlSource",
    ["CONFIG", "ENVIRONMENT", "GOOGLE", "AZURE", "AWS"],
)


def _strip_base_url_candidate(value: Optional[str]) -> Optional[str]:
    """Treat None, empty, and whitespace-only as unset."""
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _resolve_base_url(config_base_url: Optional[str]) -> tuple[str, BaseUrlSource]:
    """
    Resolve the public base URL and its source of truth.

    Precedence (first non-empty wins):

    1. ``THAUM_BASE_URL`` — overrides ``[server].base_url`` when set.
    2. Non-empty ``[server].base_url`` from config (may be omitted in TOML).
    3. PaaS: Cloud Run ``K_SERVICE`` + ``K_SERVICE_URL``, Azure ``WEBSITE_HOSTNAME``,
       AWS App Runner ``AWS_APP_RUNNER_SERVICE_URL``.

    Raises ``ValueError`` if nothing yields a non-empty URL.
    """
    if env_url := _strip_base_url_candidate(os.environ.get("THAUM_BASE_URL")):
        return env_url.rstrip("/"), BaseUrlSource.ENVIRONMENT

    if cfg_url := _strip_base_url_candidate(config_base_url):
        return cfg_url.rstrip("/"), BaseUrlSource.CONFIG

    if "K_SERVICE" in os.environ:
        if g_url := _strip_base_url_candidate(os.environ.get("K_SERVICE_URL")):
            return g_url.rstrip("/"), BaseUrlSource.GOOGLE

    if "WEBSITE_HOSTNAME" in os.environ:
        if az_host := _strip_base_url_candidate(os.environ.get("WEBSITE_HOSTNAME")):
            return f"https://{az_host}".rstrip("/"), BaseUrlSource.AZURE

    if "AWS_APP_RUNNER_SERVICE_URL" in os.environ:
        if aws_url := _strip_base_url_candidate(os.environ.get("AWS_APP_RUNNER_SERVICE_URL")):
            return aws_url.rstrip("/"), BaseUrlSource.AWS

    logger.critical("No base_url configured and no cloud environment detected.")
    raise ValueError(
        "System cannot determine public Base URL. Set [server].base_url, or set THAUM_BASE_URL, "
        "or run on a supported cloud host with its service URL in the environment."
    )

class LogLevel(IntEnum):
    # Custom levels match former verboselogs ordering (between DEBUG/INFO/WARNING).
    SPAM = 5
    DEBUG = logging.DEBUG
    VERBOSE = 15
    INFO = logging.INFO
    NOTICE = 25
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    CRITICAL = logging.CRITICAL
class AlertPriority(StrEnum):
    NORMAL = auto()
    HIGH   = auto()

@dataclass
class ThaumPerson:
    email: str
    display_name: Optional[str] = None
    platform_ids: Dict[str, str] = field(default_factory=dict)
    source_plugin: str = "unknown"

    @property
    def for_display(self) -> str:
        if self.display_name:
            return self.display_name
        return self.email


@dataclass
class ThaumTeam:
    bot: 'BaseChatBot'
    team_name: str

    lookup_id: str | None = None     # DN or canonical directory key
    alert_id: str | None = None      # Jira team ID

    _members: list[ThaumPerson] = field(default_factory=list)
    last_cached: float = field(default_factory=time.time)
    ttl: int = 14400  # 4 hours

    @property
    def is_fresh(self) -> bool:
        return (time.time() - self.last_cached) < self.ttl

    def get_members(self) -> list[ThaumPerson]:
        """Return members, refreshing from lookup plugin if stale."""
        lookup = self.bot.lookup_plugin

        if not self.is_fresh and lookup is not None:
            try:
                new_members = lookup.lookup_team_members(self)
                # Record first lookup attempt even when team has zero members.
                self._members = list(new_members)
                self.last_cached = time.time()
            except Exception as e:
                # Log through the bot
                self.bot.log.warning(f"Failed to refresh membership for team '{self.team_name}': {e}")

        return list(self._members)
# -- End ThaumTeam

@dataclass
class RespondersList:
    people: List[ThaumPerson] = field(default_factory=list)
    teams: List[ThaumTeam] = field(default_factory=list)

    def get_responders(self) -> List[ThaumPerson]:
        responders = list(self.people)
        for team in self.teams:
            responders.extend(team.get_members())
        return responders

    def __add__(self, other: object) -> "RespondersList":
        if isinstance(other, RespondersList):
            return RespondersList(
                people=[*self.people, *other.people],
                teams=[*self.teams, *other.teams],
            )
        if isinstance(other, ThaumPerson):
            return RespondersList(people=[*self.people, other], teams=list(self.teams))
        if isinstance(other, ThaumTeam):
            return RespondersList(people=list(self.people), teams=[*self.teams, other])
        return NotImplemented

    def __radd__(self, other: object) -> "RespondersList":
        if other == 0:
            return self
        return self.__add__(other)
# -- End RespondersList

# -- Pydantic config classes
class ServerDatabaseConfig(BaseModel):
    """``[server.database]``: app DB URL, field-encryption vault, DEK rotation."""

    # SQLAlchemy URL; empty/unset -> bundled PostgreSQL URL or error (see thaum.db_bootstrap.resolve_app_db_url).
    db_url: OptionalResolvedSecret = None
    database_vault_passphrase: OptionalResolvedSecret = None
    data_key_rotate_days: int = 60

    model_config = ConfigDict(extra="forbid", validate_assignment=False)


class ServerAdminConfig(BaseModel):
    """``[server.admin]``: signed HTTP admin (e.g. POST /{route_id}/log-level)."""

    route_id: str = ""
    hmac_secret_b64url: OptionalResolvedSecret = None
    clock_skew_seconds: int = 300
    log_state_poll_seconds: float = 0.0

    model_config = ConfigDict(extra="forbid", validate_assignment=False)


class ServerElectionConfig(BaseModel):
    """``[server.election]``: leader election (gemstone_utils.election)."""

    namespace: str = "thaum"
    lease_seconds: int = 60
    heartbeat_seconds: float = 15.0
    # Non-leader workers wait this long for leader init barrier (see thaum.leader_bootstrap).
    leader_init_wait_timeout_seconds: float = 300.0

    model_config = ConfigDict(extra="forbid", validate_assignment=False)


class ServerConfig(BaseModel):
    # Optional in TOML; after ``resolve_url`` this is always a non-empty str (or validation raises).
    base_url: Optional[str] = None
    url_source: Optional[BaseUrlSource] = None
    bot_url_prefix: Optional[str] = '/bot'
    bot_type: str
    lookup_plugin: str = "null"
    database: ServerDatabaseConfig = Field(default_factory=ServerDatabaseConfig)
    admin: ServerAdminConfig = Field(default_factory=ServerAdminConfig)
    election: ServerElectionConfig = Field(default_factory=ServerElectionConfig)
    model_config = ConfigDict(
        extra='forbid',          # Reject extra keys in TOML (Prevents typos)
        #frozen=True,             # Make the config immutable after load (Safety!)
        # resolve_url assigns base_url; validate_assignment=True can recurse on Pydantic v2.
        validate_assignment=False,
    )
    @model_validator(mode='after')
    def resolve_url(self) -> 'ServerConfig':
        # This function runs after fields are set
        (self.base_url,self.url_source) = _resolve_base_url(self.base_url)
        return self
    # -- End resolve_url
# -- End ServerConfig

DEFAULT_LOG_FILE_PATH = "/var/log/thaum/thaum.log"


def _normalize_log_file_value(v: object) -> Optional[str]:
    """
    Opt-in file logging: None/false/0/no → off; true/1/yes → default path; else path string.
    """
    if v is None:
        return None
    if isinstance(v, bool):
        return DEFAULT_LOG_FILE_PATH if v else None
    if isinstance(v, int):
        if v == 0:
            return None
        if v == 1:
            return DEFAULT_LOG_FILE_PATH
        raise ValueError(f"logging.file: invalid integer {v!r}; use 0 or 1, or a path string.")
    s = str(v).strip()
    if not s:
        return None
    low = s.lower()
    if low in ("no", "false", "0"):
        return None
    if low in ("yes", "true", "1"):
        return DEFAULT_LOG_FILE_PATH
    return s


LogFileSetting = Annotated[Optional[str], BeforeValidator(_normalize_log_file_value)]

LogLevelSetting = Annotated[
    LogLevel,
    # IntEnum rejects str names in Pydantic; map config strings to members explicitly.
    BeforeValidator(lambda v: LogLevel[v.strip().upper()] if isinstance(v, str) else v),
]


class LogConfig(BaseModel):
    level: LogLevelSetting = LogLevel.INFO
    timezone: str = "UTC"
    no_timestamp: bool = False
    fractional_seconds: bool = False
    file: LogFileSetting = None
    file_backup_count: int = 5
    model_config = ConfigDict(
        extra='forbid',          # Reject extra keys in TOML (Prevents typos)
        frozen=True,             # Make the config immutable after load (Safety!)
        validate_assignment=True # Validate if someone changes a value after boot
    )
# -- End LogConfig
