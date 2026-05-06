#!/usr/bin/env python3
# SPDX-License-Identifier: MPL-2.0
# Copyright 2026 Clinton Bunch
# scripts/python/thaum_config_check.py
"""
Validate Thaum configuration: ``--schema-check`` (no secret resolution) or
``--test-config`` (full resolution + DB connectivity test).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logger = logging.getLogger("thaum_config_check")


def _enable_azexp_backend() -> None:
    """Register ``azexp:`` Key Vault backend before config validation (optional dependency)."""
    try:
        import gemstone_utils.experimental.azexp_backend  # noqa: F401
    except ImportError:
        pass


def run_schema_check(config_path: str) -> None:
    from bootstrap import validate_config_after_load
    from config import load_and_validate
    from thaum.types import schema_only_validation

    with schema_only_validation():
        config = load_and_validate(config_path)
        validate_config_after_load(config)


def run_test_config(config_path: str) -> None:
    _enable_azexp_backend()
    from bootstrap import validate_config_after_load
    from config import load_and_validate
    from thaum.db_bootstrap import resolve_app_db_url, verify_app_db_connection

    config = load_and_validate(config_path)
    validate_config_after_load(config)
    server = config["server"]
    db_url = resolve_app_db_url(server)
    verify_app_db_connection(db_url)


def main() -> None:
    try:
        parser = argparse.ArgumentParser(
            description="Validate Thaum TOML configuration.",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog=(
                "--schema-check: TOML + Pydantic validation only; secret references are not resolved "
                "(suitable for CI without secrets).\n"
                "--test-config: full validation including secret resolution and a SELECT 1 DB check; "
                "run on the target host with secrets available.\n"
                "Encrypted config values still require set_keyctx_resolver at runtime.\n"
                "[server].base_url is optional when THAUM_BASE_URL or a supported cloud env provides the URL; "
                "when THAUM_BASE_URL is set it overrides base_url. CI may set THAUM_BASE_URL for --schema-check."
            ),
        )
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument(
            "--schema-check",
            action="store_true",
            help="Validate structure and types without resolving secrets or connecting to the DB.",
        )
        mode.add_argument(
            "--test-config",
            action="store_true",
            help="Full validation, resolve secrets, and test database connectivity (SELECT 1).",
        )
        parser.add_argument(
            "-c",
            "--config",
            dest="config_path",
            default=None,
            help="Path to config TOML (default: same resolution as the app — see thaum.paths.resolve_config_path).",
        )
        args = parser.parse_args()

        logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s", stream=sys.stderr)

        from thaum.paths import resolve_config_path

        config_path = args.config_path if args.config_path is not None else resolve_config_path()

        if args.schema_check:
            run_schema_check(config_path)
        else:
            run_test_config(config_path)
    except SystemExit:
        raise
    except Exception as e:
        logger.error("%s", e)
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
