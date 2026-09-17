#!/usr/bin/env python3
"""The catalog and every plugin it names, read the way Hum reads them: the catalog at
.hum-plugin/marketplace.json, a plugin's manifest at plugins/<name>/.hum-plugin/plugin.json.

"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def fail(msg: str) -> None:
    print(f"FAIL {msg}")
    fail.count += 1   # type: ignore[attr-defined]


fail.count = 0   # type: ignore[attr-defined]


def read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        fail(f"{p.relative_to(ROOT)}: {e}")
        return None


def main() -> int:
    cat = read_json(ROOT / ".hum-plugin" / "marketplace.json")
    if not isinstance(cat, dict) or not isinstance(cat.get("plugins"), list):
        fail("marketplace.json: a catalog lists its plugins under \"plugins\"")
        return 1
    seen: set[str] = set()
    for e in cat["plugins"]:
        name = str(e.get("name") or "")
        if not NAME.match(name):
            fail(f"catalog entry {name!r}: not a plain identifier")
            continue
        if name in seen:
            fail(f"catalog entry {name}: listed twice")
        seen.add(name)
        src = e.get("source")
        if not isinstance(src, str) or src.startswith(("http://", "https://")):
            fail(f"{name}: source must be a path inside this repository")
            continue
        d = (ROOT / src).resolve()
        if ROOT not in d.parents or not d.is_dir():
            fail(f"{name}: source {src} is not a directory in this repository")
            continue
        mp = d / ".hum-plugin" / "plugin.json"
        if mp.is_file():
            m = read_json(mp)
            if isinstance(m, dict) and m.get("name") not in (None, name):
                fail(f"{name}: plugin.json names it {m.get('name')!r}")
        for f in (d / ".mcp.json", d / ".lsp.json"):
            if not f.is_file():
                continue
            doc = read_json(f)
            if f.name == ".lsp.json" and isinstance(doc, dict):
                for sname, spec in doc.items():
                    if not isinstance(spec, dict) or not spec.get("command"):
                        fail(f"{name}: .lsp.json server {sname}: no command")
                    elif not isinstance(spec.get("extensionToLanguage"), dict) or not spec["extensionToLanguage"]:
                        fail(f"{name}: .lsp.json server {sname}: no extensionToLanguage")
        parts = [p for p in ("skills", "agents", "hooks", ".mcp.json", ".lsp.json") if (d / p).exists()]
        print(f"ok   {name:<20} {', '.join(parts) or 'manifest only'}")
    for d in sorted((ROOT / "plugins").iterdir()):
        if d.is_dir() and d.name not in seen:
            fail(f"plugins/{d.name} is not in the catalog")
    return 1 if fail.count else 0   # type: ignore[attr-defined]


if __name__ == "__main__":
    sys.exit(main())
