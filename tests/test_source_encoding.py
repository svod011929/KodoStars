"""Guard against UTF-8 corruption of Russian strings in the source tree.

Editing files with tools that assume a legacy code page turns «не задан» into
«РЅРµ Р·Р°РґР°РЅ» and may prepend a BOM. Tests would still pass (they rarely assert on
those strings), so check the bytes directly.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = ("app", "tests", "main.py", "README.md", ".env.example")
# UTF-8 Cyrillic decoded as cp1251 and re-encoded: a Cyrillic capital Er/Es followed
# by the second-byte artefacts (°µЅёЎџ / Ѓ‚Њ).
MOJIBAKE = re.compile(r"Р[°µЅёЎџ]|С[Ѓ‚Њ]|РІ|Р¶|Р·|в†’|вЂ")


def _files() -> list[Path]:
    out: list[Path] = []
    for entry in SOURCE_DIRS:
        path = REPO_ROOT / entry
        if path.is_file():
            out.append(path)
        else:
            out.extend(p for p in path.rglob("*") if p.is_file() and p.suffix in {".py", ".md", ".mako"})
    return out


def test_no_utf8_bom_in_sources() -> None:
    with_bom = [str(p.relative_to(REPO_ROOT)) for p in _files() if p.read_bytes()[:3] == b"\xef\xbb\xbf"]
    assert with_bom == []


def test_no_mojibake_in_sources() -> None:
    corrupted = []
    for path in _files():
        text = path.read_text(encoding="utf-8")
        if path.name == "test_source_encoding.py":
            continue
        if MOJIBAKE.search(text):
            corrupted.append(str(path.relative_to(REPO_ROOT)))
    assert corrupted == []
