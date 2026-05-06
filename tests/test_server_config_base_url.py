# SPDX-License-Identifier: MPL-2.0
# Copyright 2026 Clinton Bunch
"""Tests for [server].base_url resolution (env-first, optional TOML, PaaS fallbacks)."""

from __future__ import annotations

import os
import unittest
from contextlib import contextmanager
from typing import Dict, Iterator, Optional

from thaum.types import BaseUrlSource, ServerConfig

_BASE_URL_ENV_KEYS = frozenset(
    {
        "THAUM_BASE_URL",
        "K_SERVICE",
        "K_SERVICE_URL",
        "WEBSITE_HOSTNAME",
        "AWS_APP_RUNNER_SERVICE_URL",
    }
)


@contextmanager
def _isolated_base_url_env(overrides: Optional[Dict[str, str]] = None) -> Iterator[None]:
    """Remove base-url-related env vars, apply overrides, then restore prior values."""
    saved: Dict[str, str] = {}
    for key in _BASE_URL_ENV_KEYS:
        if key in os.environ:
            saved[key] = os.environ.pop(key)
    try:
        if overrides:
            for k, v in overrides.items():
                os.environ[k] = v
        yield
    finally:
        for key in _BASE_URL_ENV_KEYS:
            os.environ.pop(key, None)
        os.environ.update(saved)


class ServerConfigBaseUrlTest(unittest.TestCase):
    def test_omitted_base_url_with_thaum_base_url(self) -> None:
        with _isolated_base_url_env({"THAUM_BASE_URL": "https://from-env.example/"}):
            cfg = ServerConfig(bot_type="webex")
        self.assertEqual(cfg.base_url, "https://from-env.example")
        self.assertEqual(cfg.url_source, BaseUrlSource.ENVIRONMENT)

    def test_thaum_base_url_overrides_toml(self) -> None:
        with _isolated_base_url_env({"THAUM_BASE_URL": "https://env-wins.example"}):
            cfg = ServerConfig(base_url="https://from-toml.example", bot_type="webex")
        self.assertEqual(cfg.base_url, "https://env-wins.example")
        self.assertEqual(cfg.url_source, BaseUrlSource.ENVIRONMENT)

    def test_config_only_strips_trailing_slash(self) -> None:
        with _isolated_base_url_env():
            cfg = ServerConfig(base_url="https://cfg.example/path/", bot_type="webex")
        self.assertEqual(cfg.base_url, "https://cfg.example/path")
        self.assertEqual(cfg.url_source, BaseUrlSource.CONFIG)

    def test_unresolvable_raises(self) -> None:
        with _isolated_base_url_env():
            with self.assertRaises(ValueError) as ctx:
                ServerConfig(bot_type="webex")
        self.assertIn("public Base URL", str(ctx.exception))

    def test_google_cloud_run_url(self) -> None:
        with _isolated_base_url_env(
            {
                "K_SERVICE": "svc",
                "K_SERVICE_URL": "https://run.example/",
            }
        ):
            cfg = ServerConfig(bot_type="webex")
        self.assertEqual(cfg.base_url, "https://run.example")
        self.assertEqual(cfg.url_source, BaseUrlSource.GOOGLE)

    def test_azure_website_hostname(self) -> None:
        with _isolated_base_url_env({"WEBSITE_HOSTNAME": "app.azurewebsites.net"}):
            cfg = ServerConfig(bot_type="webex")
        self.assertEqual(cfg.base_url, "https://app.azurewebsites.net")
        self.assertEqual(cfg.url_source, BaseUrlSource.AZURE)

    def test_aws_app_runner_url(self) -> None:
        with _isolated_base_url_env(
            {"AWS_APP_RUNNER_SERVICE_URL": "https://abc.us-east-1.awsapprunner.com/"}
        ):
            cfg = ServerConfig(bot_type="webex")
        self.assertEqual(cfg.base_url, "https://abc.us-east-1.awsapprunner.com")
        self.assertEqual(cfg.url_source, BaseUrlSource.AWS)


if __name__ == "__main__":
    unittest.main()
