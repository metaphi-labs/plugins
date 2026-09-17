"""The gate for the reference panel case: the mapset is written in HLASM's columns and
carries the shop's frame, the program is pseudo-conversational, and no symbolic map
copybook was written by hand. Exit 0 when every check holds."""
import glob
import re
import sys

problems = []
bms = glob.glob("BMS/*.bms") + glob.glob("bms/*.bms")
if not bms:
    problems.append("no BMS/<MAPSET>.bms in the unit")
fields = []
for path in bms:
    cards = open(path, encoding="latin-1").read().split("\n")
    for n, card in enumerate(cards, 1):
        if len(card) > 72:
            problems.append(f"{path}:{n}: text past column 72")
        if len(card) == 72 and card[71] == " ":
            pass
    stmt = ""
    for n, card in enumerate(cards, 1):
        if card.startswith("*") or not card.strip():
            continue
        body = card[:71]
        cont = len(card) >= 72 and card[71] != " "
        if stmt:
            if card[:15].strip():
                problems.append(f"{path}:{n}: a continued statement resumes in column 16")
            stmt += body[15:]
        else:
            stmt = body
        if cont:
            continue
        m = re.match(r"(\S*)\s+DFHMDF\s+(.*)", stmt)
        stmt = ""
        if not m:
            continue
        ops = m.group(2)
        pos = re.search(r"POS=\((\d+),(\d+)\)", ops)
        ln = re.search(r"LENGTH=(\d+)", ops)
        ini = re.search(r"INITIAL='([^']*)'", ops)
        if pos and ln:
            r, c, L = int(pos.group(1)), int(pos.group(2)), int(ln.group(1))
            if c + L > 80:
                problems.append(f"{path}: field at ({r},{c}) LENGTH={L} runs past column 80")
            fields.append((r, c, L, ini.group(1) if ini else None, m.group(1)))

def has(row, col, text=None, length=None):
    for r, c, L, i, _n in fields:
        if r == row and c == col and (text is None or (i or "").startswith(text)) and (length is None or L == length):
            return True
    return False

if fields:
    for row in (1, 3, 22):
        if not has(row, 1, "---", 79):
            problems.append(f"row {row}: no dashed rule of 79 dashes at column 1")
    if not has(2, 1, "DATE :"):
        problems.append("row 2: no 'DATE :' label at column 1")
    if not has(2, 65, "TIME :"):
        problems.append("row 2: no 'TIME :' label at column 65")
    if not has(2, 31, "CICS EMS Consumer", 17):
        problems.append("row 2: title 'CICS EMS Consumer' is not centred at column 31")
    for row, label in ((6, "SERVER"), (8, "Destination"), (10, "Message")):
        if not any(r == row and c == 1 and (i or "").startswith(label) and (i or "").rstrip().endswith(":") and len((i or "").rstrip()) == 14
                   for r, c, L, i, _n in fields):
            problems.append(f"row {row}: label '{label}' with its colon in column 15 at column 1 is missing")
        if not any(r == row and c == 20 and n for r, c, L, i, n in fields):
            problems.append(f"row {row}: no named input field at column 20")
    if not has(21, 20, "PF3=Exit, PF5=Refresh"):
        problems.append("row 21: legend 'PF3=Exit, PF5=Refresh' at column 20 is missing")
    if not any(r == 24 and c == 1 and n for r, c, L, i, n in fields):
        problems.append("row 24: no named message line at column 1")

progs = glob.glob("Progs/*.cbl") + glob.glob("progs/*.cbl") + glob.glob("src/**/*.cbl", recursive=True)
src = "\n".join(open(p, encoding="latin-1").read().upper() for p in progs)
for need in ("RECEIVE MAP", "SEND MAP", "RETURN TRANSID", "DFHPF3", "ASKTIME", "FORMATTIME"):
    if need not in src:
        problems.append(f"no program in the unit uses {need}")
for cpy in glob.glob("Copybooks/*") + glob.glob("copybooks/*") + glob.glob("src/copy/*"):
    text = open(cpy, encoding="latin-1").read().upper()
    if re.search(r"^\s+01\s+\w+I\.", text, re.M) and "FILLER PIC X(12)" in text.replace("  ", " "):
        problems.append(f"{cpy}: a symbolic map copybook written by hand; the assembler writes it")
if not glob.glob("ORACLE/screens.json"):
    problems.append("no ORACLE/screens.json")
for p in problems:
    print(p)
sys.exit(1 if problems else 0)
