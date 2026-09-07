#!/usr/bin/env python3
"""A language server for COBOL estates: fixed-format aware, copybook aware, no dependencies.

Speaks the Language Server Protocol over stdio. Indexes every .cbl/.cob/.cpy under the workspace.

Diagnostics (published on open and on every change):
  column-72        code past column 72 on a fixed-format line: the compiler drops it without a word.
                   Columns 73-80 belong to the shop: a sequence number or a change marker (up to eight
                   letters and digits) is what they were made for and is never reported, nor is a comment
  area-a           a statement that starts in area A, or a header that does not
  undefined-data   a name used in the PROCEDURE DIVISION that no data item, paragraph or copybook declares
  undefined-para   PERFORM / GO TO a paragraph or section the program does not have
  copy-not-found   a COPY whose member is not in the workspace
  unbalanced-quote a line whose quotes do not close

Navigation: definition (data item, paragraph, section, COPY member, CALLed program), references across the
workspace, hover (the declaration line), document symbols (divisions, sections, paragraphs, data items),
workspace symbols (programs, paragraphs, 01 levels, copybooks).

Files are read as UTF-8 and, failing that, latin-1; CRLF and LF alike.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit
from urllib.request import pathname2url, url2pathname

EXTS = {".cbl", ".cob", ".cpy", ".cobol", ".copy", ".cpybk"}
COPY_EXTS = (".cpy", ".CPY", ".cbl", ".CBL", ".cob", ".COB", ".copy", ".COPY", "")
MAX_FILES = 5000
WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-_]*")
STRING = re.compile(r"'[^']*'|\"[^\"]*\"")
# a templated copybook names its items ``:XXX:-FIELD``, resolved by COPY ... REPLACING
LEVEL = re.compile(r"^\s*(\d{1,2})\s+([A-Za-z0-9:][A-Za-z0-9\-_:]*|FILLER)\b", re.I)
FILE_ENTRY = re.compile(r"^\s*(?:FD|SD)\s+([A-Za-z0-9][A-Za-z0-9\-_]*)", re.I)
SELECT_CLAUSE = re.compile(r"^\s*SELECT\s+(?:OPTIONAL\s+)?([A-Za-z0-9][A-Za-z0-9\-_]*)", re.I)
# what the identification area was made for: a sequence number or a short change marker
MARKER = re.compile(r"^\s*[A-Za-z0-9]{1,8}\s*$")
DIVISION = re.compile(r"^\s*(IDENTIFICATION|ID|ENVIRONMENT|DATA|PROCEDURE)\s+DIVISION\b", re.I)
SECTION = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9\-_]*)\s+SECTION\s*\.", re.I)
PARAGRAPH = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9\-_]*)\s*\.\s*$")
PROGRAM_ID = re.compile(r"\bPROGRAM-ID\s*\.?\s*([A-Za-z0-9][A-Za-z0-9\-_]*)", re.I)
COPY = re.compile(r"\bCOPY\s+(['\"]?)([A-Za-z0-9][A-Za-z0-9\-_]*)\1", re.I)
REPLACING_PAIR = re.compile(r"==(.*?)==\s+BY\s+==(.*?)==", re.I | re.S)
CALL = re.compile(r"\bCALL\s+(['\"])([A-Za-z0-9][A-Za-z0-9\-_]*)\1", re.I)
PERFORM = re.compile(r"\b(?:PERFORM|GO\s+TO)\s+([A-Za-z0-9][A-Za-z0-9\-_]*)", re.I)
THRU = re.compile(r"\b(?:THRU|THROUGH)\s+([A-Za-z0-9][A-Za-z0-9\-_]*)", re.I)
PIC = re.compile(r"\b(?:PIC|PICTURE)\s+(?:IS\s+)?(\S+)", re.I)
VALUE = re.compile(r"\bVALUE\s+(?:IS\s+)?(\S+(?:\s+\S+)*)", re.I)
SOURCE_FORMAT = re.compile(r">>\s*SOURCE\s+(?:FORMAT\s+)?(?:IS\s+)?(FREE|FIXED)", re.I)

STATEMENT_VERBS = {
    "ACCEPT", "ADD", "ALTER", "CALL", "CANCEL", "CLOSE", "COMPUTE", "CONTINUE", "DELETE", "DISPLAY", "DIVIDE",
    "EVALUATE", "EXEC", "EXIT", "GO", "GOBACK", "IF", "INITIALIZE", "INSPECT", "MERGE", "MOVE", "MULTIPLY", "OPEN",
    "PERFORM", "READ", "RELEASE", "RETURN", "REWRITE", "SEARCH", "SET", "SORT", "START", "STOP", "STRING",
    "SUBTRACT", "UNSTRING", "WRITE", "ELSE", "END-IF", "END-PERFORM", "END-EVALUATE", "END-READ", "END-CALL",
    "END-STRING", "END-UNSTRING", "END-COMPUTE", "END-ADD", "END-SUBTRACT", "END-MULTIPLY", "END-DIVIDE",
    "END-SEARCH", "END-WRITE", "END-REWRITE", "END-DELETE", "END-START", "END-EXEC", "WHEN", "INVOKE", "JSON",
    "XML", "ALLOCATE", "FREE", "RAISE", "RESUME", "ENTRY", "COMMIT", "ROLLBACK",
}
RESERVED = STATEMENT_VERBS | {
    "TO", "FROM", "BY", "INTO", "GIVING", "ROUNDED", "REMAINDER", "ON", "SIZE", "ERROR", "NOT", "AND", "OR", "IS",
    "ARE", "THAN", "GREATER", "LESS", "EQUAL", "EQUALS", "THEN", "TRUE", "FALSE", "OF", "IN", "UNTIL", "VARYING",
    "TIMES", "WITH", "TEST", "BEFORE", "AFTER", "THRU", "THROUGH", "END", "ALSO", "OTHER", "ANY", "USING",
    "RETURNING", "LENGTH", "DELIMITED", "DELIMITER", "POINTER", "COUNT", "TALLYING", "REPLACING", "ALL", "LEADING",
    "TRAILING", "FIRST", "CHARACTERS", "CONVERTING", "UPON", "ADVANCING", "LINE", "LINES", "PAGE", "NO", "AT",
    "INVALID", "KEY", "NEXT", "RECORD", "PREVIOUS", "INPUT", "OUTPUT", "I-O", "EXTEND", "SPACE", "SPACES", "ZERO",
    "ZEROS", "ZEROES", "HIGH-VALUE", "HIGH-VALUES", "LOW-VALUE", "LOW-VALUES", "QUOTE", "QUOTES", "NULL", "NULLS",
    "FUNCTION", "ADDRESS", "CORRESPONDING", "CORR", "SQL", "CICS", "DLI", "RUN", "SENTENCE", "PROGRAM", "CONTENT",
    "REFERENCE", "VALUE", "OMITTED", "DEPENDING", "POSITIVE", "NEGATIVE", "NUMERIC", "ALPHABETIC", "ALPHABETIC-UPPER",
    "ALPHABETIC-LOWER", "CLASS", "INITIAL", "REVERSED", "MODE", "SEQUENTIAL", "DYNAMIC", "RANDOM", "REEL", "UNIT",
    "REMOVAL", "LOCK", "CONVERSION", "EXCEPTION", "OVERFLOW", "EOP", "DATE", "DAY", "DAY-OF-WEEK", "TIME", "WHEN-COMPILED",
    "RETURN-CODE", "SORT-RETURN", "TALLY", "LINAGE-COUNTER", "SQLCODE", "SQLSTATE", "EIBCALEN", "EIBAID", "EIBTRNID",
    "DFHCOMMAREA", "DFHRESP", "DFHVALUE", "LINKAGE", "SECTION", "DIVISION", "PROCEDURE", "DATA", "WORKING-STORAGE",
    "LOCAL-STORAGE", "FILE", "FD", "SD", "SELECT", "ASSIGN", "ORGANIZATION", "ACCESS", "STATUS", "COPY", "REPLACE",
    "SUPPRESS", "INCLUDE", "DECLARE", "CURSOR", "FETCH", "SELECT", "UPDATE", "INSERT", "WHERE", "SET", "END-EXEC",
    "SYNC", "SYNCHRONIZED", "JUSTIFIED", "JUST", "RIGHT", "LEFT", "BLANK", "SIGN", "SEPARATE", "COMP", "COMP-1",
    "COMP-2", "COMP-3", "COMP-4", "COMP-5", "COMPUTATIONAL", "COMPUTATIONAL-3", "BINARY", "PACKED-DECIMAL", "DISPLAY",
    "INDEX", "INDEXED", "OCCURS", "ASCENDING", "DESCENDING", "REDEFINES", "RENAMES", "GLOBAL", "EXTERNAL", "PIC",
    "PICTURE", "USAGE", "NATIONAL", "GROUP-USAGE", "TYPEDEF", "TYPE", "ANY", "FILLER", "COMMAREA", "MAP", "MAPSET",
    "RESP", "RESP2", "SEND", "RECEIVE", "LINK", "XCTL", "RETURN", "TRANSID", "HANDLE", "CONDITION", "ABEND", "IGNORE",
    "ASKTIME", "FORMATTIME", "ABSTIME", "READQ", "WRITEQ", "TS", "TD", "QUEUE", "ITEM", "GETMAIN", "FREEMAIN", "FLENGTH",
    "SYSIN", "SYSOUT", "SYSPRINT", "STANDARD-1", "STANDARD-2", "NATIVE", "EBCDIC", "ASCII", "CURRENCY", "DECIMAL-POINT",
    "COMMA", "CONFIGURATION", "SOURCE-COMPUTER", "OBJECT-COMPUTER", "SPECIAL-NAMES", "INPUT-OUTPUT", "FILE-CONTROL",
    "I-O-CONTROL", "AUTHOR", "INSTALLATION", "DATE-WRITTEN", "DATE-COMPILED", "SECURITY", "REMARKS", "IDENTIFICATION",
    "ID", "ENVIRONMENT", "ENVIRONMENT-NAME", "ENVIRONMENT-VALUE", "ARGUMENT-NUMBER", "ARGUMENT-VALUE", "COMMAND-LINE",
    "STOP", "EXCEPTION-STATUS", "MAIN", "AS", "IF", "CRT", "SCREEN", "LABEL", "RECORDS", "STANDARD", "BLOCK", "CONTAINS",
    "RECORDING", "F", "V", "U", "S", "LINAGE", "FOOTING", "TOP", "BOTTOM", "CODE-SET", "VARYING", "ELSE", "END-IF",
}
FIGURATIVE = {"SPACE", "SPACES", "ZERO", "ZEROS", "ZEROES", "HIGH-VALUE", "HIGH-VALUES", "LOW-VALUE", "LOW-VALUES",
              "QUOTE", "QUOTES", "NULL", "NULLS", "ALL"}
SYSTEM_COPYBOOKS = {"SQLCA", "SQLDA", "DFHAID", "DFHBMSCA", "DFHEIBLK", "DFHCOMMAREA"}
SYMBOL_KIND = {"division": 3, "section": 3, "paragraph": 12, "program": 2, "data": 8, "copybook": 1}


def _uri(path: Path) -> str:
    return "file://" + pathname2url(str(path.resolve()))


def _path(uri: str) -> Path:
    u = urlsplit(uri)
    return Path(url2pathname(unquote(u.path)))


def _read(path: Path) -> str:
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _blank_literals(text: str) -> str:
    """Literals blanked, an unclosed one to the end of the line, so no word inside them is a name."""
    out = STRING.sub(lambda m: " " * len(m.group(0)), text)
    m = re.search(r"['\"]", out)
    return out[: m.start()] + " " * (len(out) - m.start()) if m else out


class Line:
    """One source line as the compiler sees it: the code area, its columns, what kind it is."""
    __slots__ = ("raw", "text", "start", "comment", "free", "overflow", "cont", "bad_indicator")

    def __init__(self, raw: str, free: bool):
        self.raw = raw.rstrip("\r\n")
        self.free = free
        self.comment = False
        self.cont = False
        self.overflow = ""
        self.bad_indicator = ""
        if free:
            self.start = 0
            t = self.raw
            self.comment = t.lstrip().startswith("*>") or t.lstrip().startswith("*")
            self.text = "" if self.comment else t
            return
        ind = self.raw[6] if len(self.raw) > 6 else " "
        self.comment = ind in "*/$"
        self.cont = ind == "-"
        self.bad_indicator = ind if ind not in " */$-Dd" else ""
        self.start = 7
        body = self.raw[7:72]
        past = self.raw[72:]
        if past.strip() and not MARKER.match(past) and not self.comment:
            self.overflow = past
        self.text = "" if self.comment else body


class Program:
    """One parsed file: its lines, names, declarations, and everything that references a name."""

    def __init__(self, path: Path, text: str, index: "Index"):
        self.path, self.index = path, index
        self.uri = _uri(path)
        free = bool(SOURCE_FORMAT.search(text[:2000]) and SOURCE_FORMAT.search(text[:2000]).group(1).upper() == "FREE")
        if not free and text and not re.match(r"^[ 0-9]{6}[ *\-/$D]", text.split("\n", 1)[0].ljust(7)):
            # no sequence area at all: a file written free-format without the directive
            first = text.split("\n", 1)[0]
            free = bool(first.strip()) and not first.startswith("      ") and not first[:6].strip().isdigit()
        self.free = free
        self.lines = [Line(ln, free) for ln in text.split("\n")]
        self.program_id = ""
        self.divisions: list[tuple[str, int]] = []
        self.sections: dict[str, int] = {}
        self.paragraphs: dict[str, int] = {}
        self.data: dict[str, list[tuple[int, int]]] = {}   # NAME → [(line, level)]
        self.copies: list[tuple[str, int, list[tuple[str, str]]]] = []   # (BOOK, line, REPLACING pairs)
        self.calls: list[tuple[str, int]] = []
        self.performs: list[tuple[str, int]] = []
        self.words: list[tuple[str, int, int]] = []   # every code word: (NAME, line, col)
        self.procedure_at: int | None = None
        self.data_at: int | None = None
        self.diagnostics: list[dict] = []
        self._parse()

    # -- parsing ----------------------------------------------------------------------------------
    def _parse(self) -> None:
        current_division = ""
        for i, ln in enumerate(self.lines):
            if ln.comment or not ln.text.strip() or ln.bad_indicator:
                continue   # a line with a bad indicator is said once, as that; its words are not names
            code = _blank_literals(ln.text)   # literals are not names
            m = DIVISION.match(code)
            if m:
                current_division = m.group(1).upper()
                if current_division == "ID":
                    current_division = "IDENTIFICATION"
                self.divisions.append((current_division, i))
                if current_division == "PROCEDURE":
                    self.procedure_at = i
                if current_division == "DATA":
                    self.data_at = i
            pm = PROGRAM_ID.search(code)
            if pm and not self.program_id:
                self.program_id = pm.group(1).upper()
            for cm in COPY.finditer(code):
                self.copies.append((cm.group(2).upper(), i, self._replacing(i, cm.end())))
            for cm in CALL.finditer(ln.text):
                self.calls.append((cm.group(2).upper(), i))
            if current_division == "PROCEDURE":
                sm = SECTION.match(code)
                if sm and ln.text[:4].strip():
                    self.sections.setdefault(sm.group(1).upper(), i)
                elif PARAGRAPH.match(code) and (ln.free or ln.text[:4].strip()):
                    name = PARAGRAPH.match(code).group(1).upper()
                    if name not in RESERVED and not name.isdigit():
                        self.paragraphs.setdefault(name, i)
                for pm_ in PERFORM.finditer(code):
                    self.performs.append((pm_.group(1).upper(), i))
                for tm in THRU.finditer(code):
                    self.performs.append((tm.group(1).upper(), i))
            elif current_division in ("DATA", ""):
                lm = LEVEL.match(code)
                if lm and lm.group(2).upper() != "FILLER":
                    self.data.setdefault(lm.group(2).upper(), []).append((i, int(lm.group(1))))
                fm = FILE_ENTRY.match(code)
                if fm:
                    self.data.setdefault(fm.group(1).upper(), []).append((i, 0))
            elif current_division == "ENVIRONMENT":
                sm_ = SELECT_CLAUSE.match(code)
                if sm_:
                    self.data.setdefault(sm_.group(1).upper(), []).append((i, 0))
            for wm in WORD.finditer(code):
                self.words.append((wm.group(0).upper(), i, ln.start + wm.start()))
        self._diagnose()

    def _replacing(self, line: int, col: int) -> list[tuple[str, str]]:
        """The ``REPLACING ==a== BY ==b==`` pairs of the COPY statement that starts at ``col`` on
        ``line``, read to its period across the cards it spans; empty for a plain COPY."""
        text, j = self.lines[line].text[col:], line + 1
        while not re.search(r"\.\s*$", text) and j < len(self.lines) and j < line + 12:
            if not self.lines[j].comment:
                text += " " + self.lines[j].text
            j += 1
        if not re.match(r"\s*REPLACING\b", text, re.I):
            return []
        return [(a.strip().upper(), b.strip().upper()) for a, b in REPLACING_PAIR.findall(text)]

    def _diagnose(self) -> None:
        out: list[dict] = []

        def diag(line: int, col: int, end: int, sev: int, code: str, msg: str) -> None:
            out.append({"range": {"start": {"line": line, "character": col}, "end": {"line": line, "character": end}},
                        "severity": sev, "code": code, "source": "cobol-lsp", "message": msg})

        in_proc = False
        for i, ln in enumerate(self.lines):
            if ln.overflow:
                diag(i, 72, len(ln.raw), 1, "column-72",
                     f"text past column 72 is ignored by the compiler: {ln.overflow.strip()!r} never compiles. "
                     "Break the line.")
            if ln.bad_indicator:
                diag(i, 6, 7, 1, "indicator", f"column 7 holds {ln.bad_indicator!r}: the indicator column takes a blank, "
                     "*, /, - or D. The statement is read from column 8, so this one is mangled")
            if ln.comment or not ln.text.strip():
                continue
            if (ln.text.count("'") % 2) or (ln.text.count('"') % 2):
                if not ln.cont and not any(self.lines[j].cont for j in (i + 1,) if j < len(self.lines)):
                    diag(i, ln.start, ln.start + len(ln.text), 1, "unbalanced-quote", "a quote on this line never closes")
            code = _blank_literals(ln.text)
            if DIVISION.match(code):
                in_proc = bool(re.match(r"^\s*PROCEDURE", code, re.I))
            if not ln.free:
                first = code[:4].strip()
                body_first = code.strip().split()[0].upper() if code.strip() else ""
                if first and in_proc and body_first in STATEMENT_VERBS and not PARAGRAPH.match(code):
                    diag(i, ln.start, ln.start + 4, 2, "area-a",
                         f"{body_first} starts in area A (columns 8-11); statements belong in area B (column 12 on)")
                if not first and (DIVISION.match(code) or SECTION.match(code)):
                    diag(i, ln.start, ln.start + len(code), 2, "area-a",
                         "a DIVISION or SECTION header belongs in area A (columns 8-11)")
        # what the program declares, copybooks included
        declared, unresolved = self.index.declared(self)
        for name, i, _pairs in self.copies:
            if self.index.copybook(name) is None:
                system = name.startswith(("DFH", "SQL")) or name in SYSTEM_COPYBOOKS
                diag(i, self.lines[i].start, self.lines[i].start + len(self.lines[i].text), 3 if system else 1,
                     "copy-not-found",
                     f"COPY {name}: no copybook named {name} in the workspace" +
                     (" (a system copybook the compiler supplies)" if system else ""))
        targets = set(self.paragraphs) | set(self.sections)
        perform_targets = {name for name, _ in self.performs}
        for name, i in self.performs:
            if name not in targets and name not in RESERVED and not name.isdigit():
                diag(i, self.lines[i].start, self.lines[i].start + len(self.lines[i].text), 1, "undefined-para",
                     f"{name}: no paragraph or section of that name in this program")
        if self.procedure_at is not None and self.data_at is not None:
            sev = 3 if unresolved else 2   # a copybook we could not open may declare it: say so more quietly
            seen: set[str] = set()
            for name, i, col in self.words:
                if i <= self.procedure_at or name in seen:
                    continue
                if name in RESERVED or name in FIGURATIVE or name in declared or name in targets or name.isdigit():
                    continue
                if name.startswith(("DFH", "EIB", "SQL")):
                    continue   # CICS and DB2 names the system copybooks declare
                if name in perform_targets:
                    continue   # said once, as a missing paragraph
                if not re.match(r"^[A-Za-z]", name) or len(name) < 2:
                    continue
                line = _blank_literals(self.lines[i].text)
                before = line[: col - self.lines[i].start].upper()
                if re.search(r"\b(FUNCTION|EXEC\s+\w+|CALL|COPY|PROGRAM-ID|DFHRESP|DFHVALUE)\s*\(?\s*$", before):
                    continue
                if re.search(r"\bEXEC\b", line, re.I) or self._in_exec(i):
                    continue
                seen.add(name)
                diag(i, col, col + len(name), sev, "undefined-data",
                     f"{name} is not declared in this program" + (" or in a copybook that could be read" if not unresolved
                                                                    else "; a copybook that could not be read may declare it"))
        self.diagnostics = out

    def _in_exec(self, line: int) -> bool:
        """Inside an EXEC … END-EXEC block: SQL and CICS names are not COBOL data items."""
        for j in range(line, -1, -1):
            t = self.lines[j].text.upper()
            if "END-EXEC" in t:
                return False
            if re.search(r"\bEXEC\b", t):
                return True
        return False

    # -- lookups ----------------------------------------------------------------------------------
    def word_at(self, line: int, col: int) -> str | None:
        if line >= len(self.lines):
            return None
        ln = self.lines[line]
        rel = col - ln.start
        for m in WORD.finditer(ln.text):
            if m.start() <= rel <= m.end():
                return m.group(0).upper()
        return None

    def name_positions(self, name: str) -> list[tuple[int, int]]:
        return [(i, c) for n, i, c in self.words if n == name]

    def declaration(self, name: str) -> tuple[int, int] | None:
        """(line, col) of a data item's declaration in this file."""
        for i, _lvl in self.data.get(name, []):
            m = re.search(r"\b" + re.escape(name) + r"\b", self.lines[i].text, re.I)
            return i, self.lines[i].start + (m.start() if m else 0)
        return None

    def header(self, name: str) -> tuple[int, int] | None:
        for table in (self.paragraphs, self.sections):
            if name in table:
                i = table[name]
                m = re.search(r"\b" + re.escape(name) + r"\b", self.lines[i].text, re.I)
                return i, self.lines[i].start + (m.start() if m else 0)
        return None

    def symbols(self) -> list[dict]:
        def rng(i: int) -> dict:
            return {"start": {"line": i, "character": 0}, "end": {"line": i, "character": max(len(self.lines[i].raw), 1)}}
        out: list[dict] = []
        if self.program_id:
            out.append({"name": self.program_id, "kind": SYMBOL_KIND["program"], "range": rng(0), "selectionRange": rng(0),
                        "children": []})
        divs = sorted(self.divisions, key=lambda d: d[1])
        for k, (dname, i) in enumerate(divs):
            end = divs[k + 1][1] if k + 1 < len(divs) else len(self.lines)
            node = {"name": f"{dname} DIVISION", "kind": SYMBOL_KIND["division"], "range": rng(i), "selectionRange": rng(i),
                    "children": []}
            if dname == "PROCEDURE":
                sec_nodes: dict[str, dict] = {}
                for sname, si in sorted(self.sections.items(), key=lambda x: x[1]):
                    sec_nodes[sname] = {"name": f"{sname} SECTION", "kind": SYMBOL_KIND["section"], "range": rng(si),
                                        "selectionRange": rng(si), "children": []}
                    node["children"].append(sec_nodes[sname])
                for pname, pi in sorted(self.paragraphs.items(), key=lambda x: x[1]):
                    p = {"name": pname, "kind": SYMBOL_KIND["paragraph"], "range": rng(pi), "selectionRange": rng(pi),
                         "children": []}
                    owner = None
                    for sname, si in self.sections.items():
                        if si < pi and (owner is None or si > self.sections[owner]):
                            owner = sname
                    (sec_nodes[owner]["children"] if owner else node["children"]).append(p)
            elif dname == "DATA":
                stack: list[tuple[int, dict]] = []
                items = sorted(((j, lvl, n) for n, lst in self.data.items() for j, lvl in lst if i <= j < end),
                               key=lambda x: x[0])
                for j, lvl, n in items:
                    if lvl == 0:   # an FD or SD: the file itself; its records follow at level 01
                        node["children"].append({"name": n, "kind": SYMBOL_KIND["data"], "detail": "FD", "range": rng(j),
                                                 "selectionRange": rng(j), "children": []})
                        stack.clear()
                        continue
                    pic = PIC.search(self.lines[j].text)
                    d = {"name": n, "kind": SYMBOL_KIND["data"], "detail": f"{lvl:02d}" + (f" PIC {pic.group(1)}" if pic else ""),
                         "range": rng(j), "selectionRange": rng(j), "children": []}
                    while stack and stack[-1][0] >= lvl:
                        stack.pop()
                    (stack[-1][1]["children"] if stack else node["children"]).append(d)
                    if lvl in (1, 77, 66, 88) and lvl != 1:
                        continue
                    stack.append((lvl, d))
            out.append(node)
        return out

    def hover_for(self, name: str) -> str | None:
        d = self.declaration(name)
        if d is not None:
            i = d[0]
            text = self.lines[i].text.strip()
            where = f"{self.path.name}:{i + 1}"
            return f"{text}\n\n{where}"
        h = self.header(name)
        if h is not None:
            kind = "section" if name in self.sections else "paragraph"
            owner = ""
            for sname, si in self.sections.items():
                if si < h[0]:
                    owner = f" in {sname} SECTION"
            return f"{kind} {name}{owner}\n\n{self.path.name}:{h[0] + 1}"
        return None


def _replaced(name: str, pairs: list[tuple[str, str]]) -> str:
    """``name`` as COPY REPLACING spells it in the program."""
    for a, b in pairs:
        name = name.replace(a, b)
    return name


class Index:
    """The workspace: every COBOL file, parsed on demand and kept while unchanged; copybooks by name."""

    def __init__(self, root: Path):
        self.root = root
        self.files: dict[Path, tuple[float, Program]] = {}
        self.open_text: dict[Path, str] = {}
        self.paths: list[Path] = []
        self.scan()

    def scan(self) -> None:
        found: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in ("node_modules", "target", "dist")]
            for f in filenames:
                if Path(f).suffix.lower() in EXTS:
                    found.append(Path(dirpath) / f)
                    if len(found) >= MAX_FILES:
                        self.paths = found
                        return
        self.paths = found

    def program(self, path: Path) -> Program | None:
        path = path.resolve()
        if path in self.open_text:
            stamp = -1.0
            cached = self.files.get(path)
            if cached and cached[0] == stamp and cached[1] is not None and getattr(cached[1], "_open_text", None) == self.open_text[path]:
                return cached[1]
            p = Program(path, self.open_text[path], self)
            p._open_text = self.open_text[path]  # type: ignore[attr-defined]
            self.files[path] = (stamp, p)
            return p
        try:
            stamp = path.stat().st_mtime
        except OSError:
            return None
        cached = self.files.get(path)
        if cached and cached[0] == stamp:
            return cached[1]
        try:
            p = Program(path, _read(path), self)
        except OSError:
            return None
        self.files[path] = (stamp, p)
        return p

    def copybook(self, name: str) -> Path | None:
        lname = name.lower()
        for p in self.paths:
            if p.stem.lower() == lname and p.suffix.lower() in (".cpy", ".copy", ".cpybk"):
                return p
        for p in self.paths:
            if p.stem.lower() == lname:
                return p
        return None

    def program_named(self, name: str) -> Path | None:
        lname = name.lower()
        for p in self.paths:
            if p.stem.lower() == lname and p.suffix.lower() in (".cbl", ".cob", ".cobol"):
                return p
        for p in self.paths:
            prog = self.program(p)
            if prog and prog.program_id.lower() == lname:
                return p
        return None

    def declared(self, prog: Program, seen: set[Path] | None = None) -> tuple[set[str], bool]:
        """Every data name a program declares, its copybooks followed; and whether one could not be read.
        A book copied twice under two REPLACING prefixes declares both sets; ``seen`` only breaks a cycle."""
        seen = seen if seen is not None else set()
        names = set(prog.data)
        unresolved = False
        for cname, _, pairs in prog.copies:
            cp = self.copybook(cname)
            if cp is None:
                unresolved = True
                continue
            key = cp.resolve()
            if key in seen:
                continue
            sub = self.program(cp)
            if sub is None:
                unresolved = True
                continue
            seen.add(key)
            more, unres = self.declared(sub, seen)
            seen.discard(key)
            names |= {_replaced(n, pairs) for n in more}
            unresolved = unresolved or unres
        return names, unresolved

    def find_declaration(self, prog: Program, name: str, seen: set[Path] | None = None) -> tuple[Path, int, int] | None:
        seen = seen if seen is not None else set()
        d = prog.declaration(name)
        if d is not None:
            return prog.path, d[0], d[1]
        for cname, _, pairs in prog.copies:
            cp = self.copybook(cname)
            if cp is None or cp.resolve() in seen:
                continue
            sub = self.program(cp)
            if sub is None:
                continue
            seen.add(cp.resolve())
            # the name as the book spells it: a REPLACING pair may have rewritten it
            wanted = [name] if not pairs else [n for n in self.declared(sub, set(seen))[0] if _replaced(n, pairs) == name]
            got = next((g for w in wanted for g in [self.find_declaration(sub, w, seen)] if g is not None), None)
            seen.discard(cp.resolve())
            if got is not None:
                return got
        return None


class Server:
    def __init__(self) -> None:
        self.index: Index | None = None
        self.inp = sys.stdin.buffer
        self.out = sys.stdout.buffer

    # -- wire -------------------------------------------------------------------------------------
    def read(self) -> dict | None:
        length = -1
        while True:
            line = self.inp.readline()
            if not line:
                return None
            if line in (b"\r\n", b"\n"):
                break
            k, _, v = line.decode("ascii", "replace").partition(":")
            if k.strip().lower() == "content-length":
                length = int(v.strip())
        if length < 0:
            return {}
        return json.loads(self.inp.read(length).decode("utf-8"))

    def send(self, msg: dict) -> None:
        body = json.dumps(msg).encode("utf-8")
        self.out.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
        self.out.flush()

    def reply(self, rid, result) -> None:
        self.send({"jsonrpc": "2.0", "id": rid, "result": result})

    def notify(self, method: str, params: dict) -> None:
        self.send({"jsonrpc": "2.0", "method": method, "params": params})

    # -- loop -------------------------------------------------------------------------------------
    def run(self) -> None:
        while True:
            msg = self.read()
            if msg is None:
                return
            method, rid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
            try:
                if method == "initialize":
                    root = params.get("rootUri") or (params.get("workspaceFolders") or [{}])[0].get("uri")
                    rp = _path(root) if root else Path(params.get("rootPath") or os.getcwd())
                    self.index = Index(rp)
                    self.reply(rid, {"capabilities": {"textDocumentSync": 1, "definitionProvider": True,
                                                      "referencesProvider": True, "hoverProvider": True,
                                                      "documentSymbolProvider": True, "workspaceSymbolProvider": True},
                                     "serverInfo": {"name": "cobol-lsp", "version": "1.0.0"}})
                elif method == "initialized":
                    pass
                elif method == "shutdown":
                    self.reply(rid, None)
                elif method == "exit":
                    return
                elif method in ("textDocument/didOpen", "textDocument/didChange"):
                    self.on_change(params)
                elif method == "textDocument/didClose":
                    p = _path(params["textDocument"]["uri"]).resolve()
                    self.index.open_text.pop(p, None) if self.index else None
                elif method == "textDocument/definition":
                    self.reply(rid, self.definition(params))
                elif method == "textDocument/references":
                    self.reply(rid, self.references(params))
                elif method == "textDocument/hover":
                    self.reply(rid, self.hover(params))
                elif method == "textDocument/documentSymbol":
                    prog = self.prog(params["textDocument"]["uri"])
                    self.reply(rid, prog.symbols() if prog else [])
                elif method == "workspace/symbol":
                    self.reply(rid, self.workspace_symbols(str(params.get("query") or "")))
                elif rid is not None and method is not None:
                    self.reply(rid, None)
            except Exception as e:  # one bad request never ends the server
                if rid is not None:
                    self.send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32603, "message": f"{type(e).__name__}: {e}"}})

    # -- handlers ---------------------------------------------------------------------------------
    def prog(self, uri: str) -> Program | None:
        if self.index is None:
            return None
        return self.index.program(_path(uri))

    def on_change(self, params: dict) -> None:
        if self.index is None:
            return
        td = params["textDocument"]
        p = _path(td["uri"]).resolve()
        text = td.get("text")
        if text is None:
            changes = params.get("contentChanges") or []
            text = changes[-1].get("text") if changes else None
        if text is None:
            return
        self.index.open_text[p] = text
        if p not in self.index.paths and p.suffix.lower() in EXTS:
            self.index.paths.append(p)
        # a change anywhere can change what other files see (a copybook): they re-parse on their next question
        for path in list(self.index.files):
            if path != p:
                self.index.files.pop(path, None)
        prog = self.index.program(p)
        if prog is not None:
            self.notify("textDocument/publishDiagnostics", {"uri": td["uri"], "diagnostics": prog.diagnostics})

    def _at(self, params: dict) -> tuple[Program, str] | None:
        prog = self.prog(params["textDocument"]["uri"])
        if prog is None:
            return None
        pos = params["position"]
        name = prog.word_at(pos["line"], pos["character"])
        return (prog, name) if name else None

    @staticmethod
    def _loc(path: Path, line: int, col: int, length: int = 1) -> dict:
        return {"uri": _uri(path), "range": {"start": {"line": line, "character": col},
                                              "end": {"line": line, "character": col + length}}}

    def definition(self, params: dict) -> list[dict]:
        at = self._at(params)
        if at is None or self.index is None:
            return []
        prog, name = at
        line = params["position"]["line"]
        text = prog.lines[line].text if line < len(prog.lines) else ""
        # COPY NAME → the copybook; CALL 'NAME' → the program
        if re.search(r"\bCOPY\s+['\"]?" + re.escape(name), text, re.I):
            cp = self.index.copybook(name)
            return [self._loc(cp, 0, 0)] if cp else []
        if re.search(r"\bCALL\s+['\"]" + re.escape(name), text, re.I):
            pp = self.index.program_named(name)
            if pp:
                sub = self.index.program(pp)
                pm = PROGRAM_ID.search("\n".join(x.text for x in sub.lines)) if sub else None
                li = next((i for i, x in enumerate(sub.lines) if PROGRAM_ID.search(x.text)), 0) if sub else 0
                return [self._loc(pp, li, sub.lines[li].start if sub else 0)]
            return []
        d = self.index.find_declaration(prog, name)
        if d is not None:
            return [self._loc(d[0], d[1], d[2], len(name))]
        h = prog.header(name)
        if h is not None:
            return [self._loc(prog.path, h[0], h[1], len(name))]
        pp = self.index.program_named(name)
        return [self._loc(pp, 0, 0)] if pp else []

    def references(self, params: dict) -> list[dict]:
        at = self._at(params)
        if at is None or self.index is None:
            return []
        _prog, name = at
        out: list[dict] = []
        if name in RESERVED or name in FIGURATIVE:
            return out
        for path in sorted(self.index.paths):
            p = self.index.program(path)
            if p is None:
                continue
            for i, c in p.name_positions(name):
                out.append(self._loc(path, i, c, len(name)))
        return out

    def hover(self, params: dict) -> dict | None:
        at = self._at(params)
        if at is None or self.index is None:
            return None
        prog, name = at
        text = prog.hover_for(name)
        if text is None:
            d = self.index.find_declaration(prog, name)
            if d is not None:
                sub = self.index.program(d[0])
                text = sub.hover_for(name) if sub else None
        if text is None:
            pp = self.index.program_named(name)
            if pp:
                text = f"program {name}\n\n{pp.relative_to(self.index.root) if pp.is_relative_to(self.index.root) else pp}"
        return {"contents": {"kind": "plaintext", "value": text}} if text else None

    def workspace_symbols(self, query: str) -> list[dict]:
        if self.index is None:
            return []
        q = query.upper()
        out: list[dict] = []

        def add(name: str, kind: str, path: Path, line: int, container: str = "") -> None:
            if q in name.upper():
                out.append({"name": name, "kind": SYMBOL_KIND[kind], "location": self._loc(path, line, 0),
                            "containerName": container})

        for path in sorted(self.index.paths):
            p = self.index.program(path)
            if p is None:
                continue
            if p.program_id:
                add(p.program_id, "program", path, 0)
            if path.suffix.lower() in (".cpy", ".copy", ".cpybk"):
                add(path.stem.upper(), "copybook", path, 0)
            for n, i in p.paragraphs.items():
                add(n, "paragraph", path, i, p.program_id)
            for n, i in p.sections.items():
                add(n, "section", path, i, p.program_id)
            for n, lst in p.data.items():
                for i, lvl in lst:
                    if lvl in (1, 77) or len(q) >= 3:
                        add(n, "data", path, i, p.program_id or path.stem.upper())
            if len(out) > 500:
                break
        return out[:500]


if __name__ == "__main__":
    Server().run()
