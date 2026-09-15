"""Regression: hosting panels must run repo-root main.py, not app/__main__.py.

RubyHost / Pterodactyl APP PY FILE=/home/container/app/__main__.py puts the
app/ directory on sys.path[0]. Then `from app.… import …` raises
ModuleNotFoundError: No module named 'app'.

Set APP PY FILE=main.py (project root) so sys.path[0] is the repo root.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _panel_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    return env


def _import_script_as_panel(script: Path) -> subprocess.CompletedProcess[str]:
    """Load a .py file the way a panel does: sys.path[0] = script directory.

    Uses run_name != '__main__' so we do not start polling.
    """
    loader = (
        "import runpy, sys\n"
        "from pathlib import Path\n"
        "script = Path(sys.argv[1]).resolve()\n"
        "sys.path.insert(0, str(script.parent))\n"
        "runpy.run_path(str(script), run_name='panel_entrypoint')\n"
        "print('imported_ok')\n"
    )
    return subprocess.run(
        [sys.executable, "-c", loader, str(script)],
        cwd="/tmp",
        env=_panel_env(),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_root_main_py_imports_app_package() -> None:
    result = _import_script_as_panel(REPO_ROOT / "main.py")
    assert result.returncode == 0, result.stderr
    assert "imported_ok" in result.stdout
    assert "No module named 'app'" not in result.stderr


def test_app_dunder_main_as_app_py_file_cannot_import_app() -> None:
    result = _import_script_as_panel(REPO_ROOT / "app" / "__main__.py")
    assert result.returncode != 0
    assert "No module named 'app'" in result.stderr
