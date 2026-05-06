# SPDX-License-Identifier: MPL-2.0
# Copyright 2026 Clinton Bunch
# app.py
"""
WSGI entry: ``gunicorn app:app`` (multiple workers supported: leader election registers Webex
webhooks once per deployment). Set ``server.database.database_vault_passphrase`` when using shared DB
Webex HMAC (omit ``hmac_secret`` in bot config). Config: ``THAUM_CONFIG_FILE`` if set; else the first
existing file in ``/etc/thaum/`` then ``./``, in order:
``thaum.toml``, ``thaum.conf``. If none exist, startup fails fast. See
``thaum.paths.resolve_config_path``.
"""

from __future__ import annotations

import os

from bootstrap import bootstrap, fail_fast_fatal
from log_setup import init_early_logging_from_env
from thaum.paths import ConfigResolutionError, resolve_config_path
from web import create_app

init_early_logging_from_env()
try:
    _config = bootstrap(resolve_config_path())
except ConfigResolutionError as e:
    fail_fast_fatal(str(e))
    raise


app = create_app(_config)

if __name__ == "__main__":
    app.run(
        host=os.environ.get("FLASK_RUN_HOST", "127.0.0.1"),
        port=int(os.environ.get("FLASK_RUN_PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes"),
    )
