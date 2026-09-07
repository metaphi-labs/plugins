#!/usr/bin/env python3
"""Stand between a plain LSP client and Broadcom's COBOL Language Support engine.

The engine asks its client to find copybooks (``copybook/resolve``: program URI, copybook name,
dialect; answer a file URI or null) and then to read them (``file/content``: a file URI; answer
the text or null), the way its VS Code extension does. This proxy answers both, the lookup from
the ``cobol-lsp.cpy-manager.paths-local`` folders the client sent as settings relative to the
workspace root, and passes every other message through untouched.

    proxy.py <engine> [engine args...]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname

EXTENSIONS = [".cpy", ".copy", ".cbl", ".cob", ""]
DEFAULT_PATHS = ["Copybooks", "copybooks", "CPY", "cpy", "COPY", "copy", "Copybook",
                 "*/Copybooks", "*/copybooks", "*/CPY", "*/cpy", "*/COPY", "*/copy"]

root = Path.cwd()
paths: list[str] = list(DEFAULT_PATHS)
extensions: list[str] = list(EXTENSIONS)
lock = threading.Lock()
TRACE = bool(os.environ.get("CHE4Z_PROXY_TRACE"))


def _read(stream):
    """One JSON-RPC message; a stray line before the first header (a banner, a blank) is skipped."""
    length = -1
    while True:
        line = stream.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            if length >= 0:
                break
            continue
        k, _, v = line.decode("ascii", "replace").partition(":")
        if k.strip().lower() == "content-length":
            length = int(v)
    body = stream.read(length)
    if TRACE:
        sys.stderr.write(body[:200].decode("utf-8", "replace") + "\n")
    return json.loads(body)


def _write(stream, msg) -> None:
    body = json.dumps(msg).encode()
    if TRACE:
        sys.stderr.write("> " + body[:300].decode("utf-8", "replace") + "\n")
    with lock:
        stream.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
        stream.flush()


def _path_of(uri: str) -> Path:
    return Path(url2pathname(unquote(urlsplit(uri).path)))


def _section(settings, dotted: str):
    cur = settings
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _take_settings(settings) -> None:
    global paths, extensions
    if not isinstance(settings, dict):
        return
    local = _section(settings, "cobol-lsp.cpy-manager.paths-local")
    if isinstance(local, list) and local:
        paths = [str(p) for p in local]
    exts = _section(settings, "cobol-lsp.cpy-manager.copybook-extensions")
    if isinstance(exts, list) and exts:
        extensions = [str(e) for e in exts]


def _content(uri: str) -> str | None:
    """The text of a file the engine asked for, as the estate stores it (UTF-8, else Latin-1)."""
    try:
        data = _path_of(uri).read_bytes()
    except OSError:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _resolve(program_uri: str, name: str) -> str | None:
    """The copybook ``name`` as a file URI: the program's own folder first, then every
    ``paths-local`` folder (a glob is a pattern under the root), by extension, case blind."""
    folders = [_path_of(program_uri).parent] if program_uri else []
    for p in paths:
        folders += sorted(root.glob(p)) if any(ch in p for ch in "*?[") else [root / p]
    want = {(name + e).lower() for e in extensions} | {name.lower()}
    for folder in folders:
        if not folder.is_dir():
            continue
        try:
            for entry in sorted(os.listdir(folder)):
                if entry.lower() in want:
                    return (folder / entry).resolve().as_uri()
        except OSError:
            continue
    return None


def main() -> None:
    engine = subprocess.Popen(sys.argv[1:], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    client_in, client_out = sys.stdin.buffer, sys.stdout.buffer

    def from_client() -> None:
        global root
        while True:
            msg = _read(client_in)
            if msg is None:
                break
            method, params = msg.get("method"), msg.get("params") or {}
            if method == "initialize":
                uri = params.get("rootUri") or ""
                if uri:
                    root = _path_of(uri)
                _take_settings(params.get("initializationOptions"))
            elif method == "workspace/didChangeConfiguration":
                _take_settings(params.get("settings"))
            _write(engine.stdin, msg)
        try:
            engine.stdin.close()
        except OSError:
            pass

    threading.Thread(target=from_client, daemon=True).start()
    while True:
        msg = _read(engine.stdout)
        if msg is None:
            break
        if msg.get("method") == "copybook/resolve" and "id" in msg:
            args = msg.get("params") or []
            program_uri, name = (args + [None, None])[:2] if isinstance(args, list) else (None, None)
            _write(engine.stdin, {"jsonrpc": "2.0", "id": msg["id"], "result": _resolve(program_uri or "", str(name or ""))})
            continue
        if msg.get("method") == "file/content" and "id" in msg:
            uri = msg.get("params")
            uri = uri[0] if isinstance(uri, list) and uri else uri
            _write(engine.stdin, {"jsonrpc": "2.0", "id": msg["id"], "result": _content(str(uri or ""))})
            continue
        _write(client_out, msg)
    sys.exit(engine.wait())


if __name__ == "__main__":
    main()
