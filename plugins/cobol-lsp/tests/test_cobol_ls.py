"""The COBOL language server, driven over stdio the way an editor or a coding agent drives it."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[1] / "server" / "cobol_ls.py"


class Client:
    def __init__(self, root: Path):
        self.p = subprocess.Popen([sys.executable, str(SERVER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  cwd=str(root))
        self.n = 0
        self.notes: list[dict] = []
        self.request("initialize", {"rootUri": root.as_uri(), "capabilities": {}})
        self.notify("initialized", {})

    def _send(self, msg: dict) -> None:
        body = json.dumps(msg).encode()
        self.p.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
        self.p.stdin.flush()

    def _read(self) -> dict:
        length = -1
        while True:
            line = self.p.stdout.readline()
            if line in (b"\r\n", b"\n"):
                break
            k, _, v = line.decode().partition(":")
            if k.strip().lower() == "content-length":
                length = int(v)
        return json.loads(self.p.stdout.read(length))

    def notify(self, method: str, params: dict) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def request(self, method: str, params: dict):
        self.n += 1
        self._send({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params})
        while True:
            m = self._read()
            if m.get("id") == self.n:
                assert "error" not in m, m["error"]
                return m.get("result")
            self.notes.append(m)

    def open(self, path: Path) -> list[dict]:
        self.notify("textDocument/didOpen", {"textDocument": {"uri": path.as_uri(), "languageId": "cobol", "version": 1,
                                                              "text": path.read_text(encoding="latin-1")}})
        while True:
            m = self._read()
            if m.get("method") == "textDocument/publishDiagnostics":
                return m["params"]["diagnostics"]
            self.notes.append(m)

    def close(self) -> None:
        self.request("shutdown", {})
        self.notify("exit", {})
        self.p.wait(timeout=5)


@pytest.fixture
def estate(tmp_path: Path) -> Path:
    (tmp_path / "Copybooks").mkdir()
    (tmp_path / "Progs").mkdir()
    (tmp_path / "Copybooks" / "L41010.cpy").write_text(
        "       01  :XXX:-L41010-REG.\r\n             05 :XXX:-L41010-DATACHA  PIC S9(009)     COMP-3.\r\n",
        encoding="latin-1")
    (tmp_path / "Copybooks" / "CLINE.cpy").write_text(
        "       01  LINE-REC.\r\n           05  LR-QTY        PIC 9(4).\r\n           05  LR-PRICE      PIC 9(7)V99.\r\n",
        encoding="latin-1")
    (tmp_path / "Progs" / "DISC01.cbl").write_text("""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DISC01.                                              CHG00017
      ******************************************************************00000030
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT  SEQENT01  ASSIGN  TO  UT-S-SEQENT01.
       DATA DIVISION.
       FILE SECTION.
       FD  SEQENT01
           RECORDING  MODE  IS  F.
       01  E01-REG                 PIC X(80).
       WORKING-STORAGE SECTION.
       COPY CLINE.
       COPY NOSUCH.
       COPY L41010 REPLACING ==:XXX:==
                             BY  ==E01==.
       01  WS-EFF-DISC   PIC 9(2).
       01  WS-GROSS      PIC 9(9)V99.
       01  WS-TOTAL      PIC 9(9)V99.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT SEQENT01
           MOVE 1 TO E01-L41010-DATACHA
           MOVE 12 TO LR-QTY
           COMPUTE WS-GROSS = LR-QTY * LR-PRICE
           COMPUTE WS-TOTAL ROUNDED = WS-GROSS - WS-GROSS * WS-EFF-DISC / 100
           MOVE WS-TOTL TO WS-GROSS
           PERFORM SHOW-IT
           PERFORM NO-SUCH-PARA
           CALL 'DISC02' USING LINE-REC
       MOVE 1 TO WS-EFF-DISC
      MOVE 2 TO WS-EFF-DISC
           DISPLAY 'DONE
           GOBACK.
       SHOW-IT.
           DISPLAY WS-GROSS.
""", encoding="latin-1")
    (tmp_path / "Progs" / "DISC02.cbl").write_text("""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DISC02.
       DATA DIVISION.
       LINKAGE SECTION.
       COPY CLINE.
       PROCEDURE DIVISION USING LINE-REC.
           DISPLAY LR-QTY
           GOBACK.
""", encoding="latin-1")
    return tmp_path


def test_diagnostics_name_every_planted_defect_and_nothing_else(estate: Path):
    c = Client(estate)
    try:
        diags = c.open(estate / "Progs" / "DISC01.cbl")
        by = {(d["code"], d["range"]["start"]["line"] + 1): d["message"] for d in diags}
        assert ("column-72", 27) in by and "'/ 100'" in by[("column-72", 27)]
        assert ("copy-not-found", 15) in by
        assert ("undefined-para", 30) in by and "NO-SUCH-PARA" in by[("undefined-para", 30)]
        assert ("undefined-data", 28) in by and by[("undefined-data", 28)].startswith("WS-TOTL")
        assert ("area-a", 32) in by and "MOVE starts in area A" in by[("area-a", 32)]
        assert ("indicator", 33) in by and "'M'" in by[("indicator", 33)]
        assert ("unbalanced-quote", 34) in by
        # a change marker at column 73 on a code line, a sequence number on a comment line: never overflow
        assert not any(d["code"] == "column-72" and d["range"]["start"]["line"] + 1 in (2, 3) for d in diags)
        # a name a COPY REPLACING pair spells is declared, and the file names FD and SELECT declare are names
        assert not any(d["message"].startswith("E01-L41010") for d in diags)
        assert not any(d["code"] == "undefined-data" and d["message"].startswith("SEQENT01") for d in diags)
        codes = sorted(d["code"] for d in diags)
        assert codes == sorted(["area-a", "column-72", "copy-not-found", "indicator", "undefined-data",
                                "undefined-para", "unbalanced-quote"]), codes
        # a name a copybook declares is not undefined; with a copybook missing the verdict is information, not warning
        assert all(d["severity"] == 3 for d in diags if d["code"] == "undefined-data")
    finally:
        c.close()


def test_navigation_follows_copybooks_paragraphs_and_calls(estate: Path):
    c = Client(estate)
    prog = estate / "Progs" / "DISC01.cbl"
    try:
        c.open(prog)
        td = {"uri": prog.as_uri()}
        d = c.request("textDocument/definition", {"textDocument": td, "position": {"line": 24, "character": 24}})
        assert d and d[0]["uri"].endswith("Copybooks/CLINE.cpy") and d[0]["range"]["start"]["line"] == 1   # LR-QTY
        d = c.request("textDocument/definition", {"textDocument": td, "position": {"line": 28, "character": 22}})
        assert d[0]["uri"].endswith("DISC01.cbl") and d[0]["range"]["start"]["line"] == 35            # SHOW-IT
        d = c.request("textDocument/definition", {"textDocument": td, "position": {"line": 30, "character": 19}})
        assert d[0]["uri"].endswith("DISC02.cbl") and d[0]["range"]["start"]["line"] == 1             # CALL 'DISC02'
        d = c.request("textDocument/definition", {"textDocument": td, "position": {"line": 13, "character": 13}})
        assert d[0]["uri"].endswith("CLINE.cpy")                                                        # COPY CLINE
        d = c.request("textDocument/definition", {"textDocument": td, "position": {"line": 23, "character": 24}})
        assert d[0]["uri"].endswith("L41010.cpy") and d[0]["range"]["start"]["line"] == 1               # REPLACING'd name
        refs = c.request("textDocument/references", {"textDocument": td, "position": {"line": 24, "character": 24}})
        where = sorted((Path(r["uri"]).name, r["range"]["start"]["line"] + 1) for r in refs)
        assert where == [("CLINE.cpy", 2), ("DISC01.cbl", 25), ("DISC01.cbl", 26), ("DISC02.cbl", 7)], where
        assert c.request("textDocument/references", {"textDocument": td, "position": {"line": 24, "character": 20}}) == []
        h = c.request("textDocument/hover", {"textDocument": td, "position": {"line": 25, "character": 40}})
        assert "LR-PRICE" in h["contents"]["value"] and "PIC 9(7)V99" in h["contents"]["value"]
        h = c.request("textDocument/hover", {"textDocument": td, "position": {"line": 28, "character": 22}})
        assert h["contents"]["value"].startswith("paragraph SHOW-IT")
        syms = c.request("textDocument/documentSymbol", {"textDocument": td})
        names = [s["name"] for s in syms]
        assert names == ["DISC01", "IDENTIFICATION DIVISION", "ENVIRONMENT DIVISION", "DATA DIVISION", "PROCEDURE DIVISION"]
        assert [s["name"] for s in syms[4]["children"]] == ["MAIN-PARA", "SHOW-IT"]
        assert [s["name"] for s in syms[3]["children"]] == ["SEQENT01", "E01-REG", "WS-EFF-DISC", "WS-GROSS", "WS-TOTAL"]
        ws = c.request("workspace/symbol", {"query": "LR-"})
        assert sorted(s["name"] for s in ws) == ["LR-PRICE", "LR-QTY"]
        ws = c.request("workspace/symbol", {"query": "DISC"})
        assert {s["name"] for s in ws} >= {"DISC01", "DISC02", "WS-EFF-DISC"}
    finally:
        c.close()


def test_a_change_republishes_and_a_fixed_line_clears(estate: Path):
    c = Client(estate)
    prog = estate / "Progs" / "DISC01.cbl"
    try:
        first = c.open(prog)
        text = prog.read_text(encoding="latin-1").replace(
            "           COMPUTE WS-TOTAL ROUNDED = WS-GROSS - WS-GROSS * WS-EFF-DISC / 100",
            "           COMPUTE WS-TOTAL ROUNDED =\n               WS-GROSS - WS-GROSS * WS-EFF-DISC / 100")
        c.notify("textDocument/didChange", {"textDocument": {"uri": prog.as_uri(), "version": 2},
                                            "contentChanges": [{"text": text}]})
        while True:
            m = c._read()
            if m.get("method") == "textDocument/publishDiagnostics":
                second = m["params"]["diagnostics"]
                break
        assert any(d["code"] == "column-72" for d in first) and not any(d["code"] == "column-72" for d in second)
    finally:
        c.close()


def test_an_unknown_request_and_a_bad_position_are_answered_not_fatal(estate: Path):
    c = Client(estate)
    try:
        assert c.request("textDocument/implementation", {"textDocument": {"uri": (estate / "x.cbl").as_uri()},
                                                         "position": {"line": 0, "character": 0}}) is None
        assert c.request("textDocument/hover", {"textDocument": {"uri": (estate / "Progs" / "DISC01.cbl").as_uri()},
                                                "position": {"line": 999, "character": 0}}) is None
        assert c.request("textDocument/documentSymbol", {"textDocument": {"uri": (estate / "nowhere.cbl").as_uri()}}) == []
    finally:
        c.close()
