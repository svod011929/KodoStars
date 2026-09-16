"""Regression: app must not shadow the stdlib logging module.

RubyHost runs via app/__main__.py with the app directory on sys.path.
A module named app/logging.py then wins over stdlib logging, and
structlog fails with AttributeError: module 'logging' has no attribute 'NOTSET'.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "app"


def test_app_has_no_logging_py() -> None:
    shadow = APP_DIR / "logging.py"
    assert not shadow.exists(), "app/logging.py shadows stdlib logging when the app directory is on sys.path"


def test_setup_logging_imports_from_log_setup() -> None:
    module = importlib.import_module("app.log_setup")

    assert callable(module.setup_logging)


def test_stdlib_logging_notset_when_app_dir_on_sys_path() -> None:
    """Reproduce the RubyHost sys.path layout: import logging must stay stdlib."""
    saved_path = sys.path[:]
    cached = {name: sys.modules.get(name) for name in ("logging", "app.logging")}
    try:
        sys.modules.pop("logging", None)
        sys.modules.pop("app.logging", None)
        sys.path.insert(0, str(APP_DIR))
        logging = importlib.import_module("logging")
        assert hasattr(logging, "NOTSET"), (
            f"import logging loaded {getattr(logging, '__file__', logging)!r} "
            "instead of stdlib (missing NOTSET)"
        )
        assert logging.NOTSET == 0
    finally:
        sys.path[:] = saved_path
        for name, module in cached.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
