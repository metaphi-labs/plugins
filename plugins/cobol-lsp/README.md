# cobol-lsp

COBOL code intelligence for estate code: fixed format, copybooks, JCL beside it. A single Python file, no dependencies.

Install: `hum plugin install cobol-lsp@metaphi`. Needs `python3` on PATH.

## Diagnostics

| Code | Says |
| --- | --- |
| `column-72` | Text past column 72 on a fixed-format line. The compiler drops it silently |
| `area-a` | A statement in area A, or a DIVISION or SECTION header outside it |
| `undefined-data` | A name in the PROCEDURE DIVISION that no data item, paragraph or copybook declares |
| `undefined-para` | PERFORM or GO TO a paragraph the program does not have |
| `copy-not-found` | COPY of a member not in the workspace |
| `unbalanced-quote` | A quote that never closes on its line |

## Navigation

Definition of a data item (copybooks followed), a paragraph or section, a COPY member, a CALLed program. References across every .cbl, .cob and .cpy in the workspace. Hover shows the declaration line. Document symbols list divisions, sections, paragraphs and data items by level; workspace symbols find programs, paragraphs, 01 levels and copybooks by name.
