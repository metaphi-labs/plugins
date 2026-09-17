---
name: cics-screens
description: Build a CICS online screen the shop way. The map is BMS macro source assembled on the emulator, the panel follows the shop standard, the program is pseudo-conversational, and a screen counts as built only when a transaction has run through it.
---

# CICS online screens

An online screen is the black terminal screen a mainframe user works on. Every screen has a map, written as BMS macro source, which declares the fields, their positions and their attributes the way an HTML form declares inputs. Behind the map runs a CICS program that receives what the user typed, does the work, sends the map back and hands the next attention key to the next task. Build all three, in that order, and prove them together.

## What counts as built

A screen exists when its mapset assembled from macro source on the emulator and one transaction ran through it with the map rendered in the report. Nothing less is a screen.

- Ship the mapset as `BMS/<MAPSET>.bms`. The emulator assembles it before any compile, writes the symbolic map copybook the program COPYs, and paints every map the transaction SENDs onto the physical map. The report carries `cics.bms.assembled` and `cics.screens_out`, one rendered 24 by 80 screen per SEND.
- Never write the symbolic map copybook by hand. The copybook is an output of the assembler. A program that SENDs a map whose mapset was never assembled abends APCT, as it does on the mainframe.
- Read the assembler's refusals as the mainframe's word. A field past column 80, a field outside the map, an unterminated string: fix the source. Do not route around the assembler and do not record it as a sandbox limitation.
- Run the case with `run_unit` on the unit that holds `BMS/`, `Progs/`, `run.json` and `ORACLE/screens.json`. Read the rendered screens in the result before you report.

## Writing the macro source

HLASM reads a card in columns. Break the rule and the assembler stops at the first card.

- The label starts in column 1, the macro name in column 10, the operands in column 16.
- Text ends at column 71. A statement that continues carries a non-blank character in column 72 and resumes in column 16 of the next card. Nothing else may stand in column 72.
- Break after a comma where one falls in the card. A quoted INITIAL longer than the card is split at column 71 and continues in column 16 with no quote in between.
- `POS=(row,col)` names the attribute byte. The field's text starts one column to the right. `LENGTH` counts the text and excludes the attribute byte, so `col + LENGTH` must stay within 80.
- Leave a stopper after every unprotected field: an unnamed `DFHMDF` with `LENGTH=1,ATTRB=ASKIP` in the column after the input, so typing stops where the field ends.
- Exactly one field carries `IC`. Field names have seven characters at most, since the assembler adds a suffix.
- `SIZE=(24,80)` on `DFHMDI` whenever the map uses `POS`.
- Colour: `COLOR=` on `DFHMSD` sets the mapset's colour, a field's own `COLOR=` overrides it. A mapset with no `COLOR=` shows in base colour, four colours by protection and intensity.

`references/EMSCON.bms` is a mapset in exactly these columns. Copy its shape.

## The panel standard

Every panel of the shop shares one frame. The body between the frame is the screen's own. Rows and columns below are the attribute byte's column, so text begins one column to the right.

| Row | Content | Columns |
|---|---|---|
| 1 | dashed rule, 79 dashes | 1 |
| 2 | `DATE : mm/dd/yy` | 1, value at 8 |
| 2 | panel title, centred, 40 characters at most | 40 minus half the title's length |
| 2 | `TIME : hh:mm:ss` | 65, value at 72 |
| 3 | dashed rule | 1 |
| 6, 8, 10, ... | field labels, one blank row between fields | 1, colon in column 15 |
| 6, 8, 10, ... | input fields | 20 |
| 21 | PF key legend | 20 |
| 22 | dashed rule | 1 |
| 24 | message line, bright | 1 |

- Labels sit in one column and their colons align. The input begins five columns after the colon. Case follows the shop: `SERVER` in capitals where the shop writes it so, `Destination` and `Message` in mixed case.
- The legend lists only the keys the screen honours, as `PFn=Verb` pairs separated by a comma and a space: `PF3=Exit, PF5=Refresh`. Every screen honours PF3. A list screen honours PF7 and PF8 for paging. Say `Exit`, `Refresh`, `Backward`, `Forward`, `Cancel`.
- The message line is a named, protected, bright field on row 24. Validation messages and confirmations go there. Nothing else does.
- The date and time on row 2 come from `ASKTIME` and `FORMATTIME` in the program on every send, formatted `MMDDYY` with `DATESEP('/')` and `TIME` with `TIMESEP(':')`.
- A management screen for one entity is two maps in one mapset: a list map for browse and select, and a detail map for create, read, update and delete. Both carry the frame.
- A title names the panel in the shop's words. Never truncate a title to fit; shorten the words.

The worked example is the reference panel an expert supplied: `references/EMSCON.bms` renders as

```
 1 -------------------------------------------------------------------------------
 2 DATE : 11/10/06               CICS EMS Consumer                 TIME : 10:16:40
 3 -------------------------------------------------------------------------------
 6 SERVER       :     _
 8 Destination  :
10 Message      :
21                    PF3=Exit, PF5=Refresh
22 -------------------------------------------------------------------------------
24 (message line)
```

## The program

The program is pseudo-conversational. Each attention key starts a fresh task; the COMMAREA carries the state between tasks.

- `EIBCALEN = 0`: first entry. Send the map with `ERASE`, the date and time stamped, and return with `TRANSID` and a COMMAREA.
- Otherwise `RECEIVE MAP` into the symbolic input map, then `EVALUATE EIBAID`: `DFHPF3` ends the conversation with a farewell `SEND TEXT` and a plain `RETURN`; `DFHPF5` re-sends; `DFHENTER` validates and acts; any other key writes an invalid-key message. Every branch stamps the clock and sends the map.
- Validation puts the message on the message line and the cursor in the offending field (`MOVE -1 TO <field>L`).
- The screen program handles screens and transitions only. Business logic and SQL live in the domain's own subroutines, which the program CALLs or LINKs to.
- Every online program is started by its transaction identifier. It has no JCL and needs none.

`references/EMSCON1.cbl` is the whole pattern in one program.

## The case and the oracle

- `run.json` declares the region and the conversation: `cics.transactions` maps the identifier to the program; `cics.screens` is one entry per attention key, with `map`, `mapset`, `aid` and `fields` by DSECT name. The first entry names the transaction alone: nothing typed, the program's first-entry path. Pin `clock` so the date and time on row 2 are the same on every run.
- `ORACLE/screens.json` grades the maps sent, one entry per SEND in send order, field by field as the screen shows them. Name the fields that carry the business result: the message line, the values echoed back, the list rows. A field whose value you do not judge takes `null` and must still be present. `"exact": true` pins the count of maps sent.
- Cover the positive path, each rejection the screen makes, and PF3. A rejection is a screen with the message line set and the cursor in the field.

`references/run.json` and `references/screens.json` are the case and the oracle for the worked example. Run them on the emulator and read the rendered screens; then write yours the same way.

## Before you report

- The mapset assembled: `cics.bms.assembled` names it and `refused` is empty.
- Every map the case reaches is in `cics.screens_out` with `rendered: true`.
- The oracle passed on the emulator, and the rendered screens look like the panel standard.
- No hand-written symbolic map copybook exists in the unit.
- The report names the unit, the transaction, the screens and the run that proved them.
