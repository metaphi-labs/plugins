       IDENTIFICATION DIVISION.
       PROGRAM-ID. EMSCON1.
      *================================================================*
      * EMS Consumer panel. Transaction EMSC, mapset EMSCON, map EMSMAP.
      * Pseudo-conversational: every attention key starts a new task
      * that reads the screen, acts, sends the panel and returns with
      * the transaction identifier so the next key comes back here.
      *================================================================*
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       COPY EMSCON.
       COPY DFHAID.
       COPY DFHBMSCA.
       01  WS-ABSTIME            PIC S9(15) COMP-3.
       01  WS-DATE               PIC X(8).
       01  WS-TIME               PIC X(8).
       01  WS-RESP               PIC S9(8) COMP.
       01  WS-BYE                PIC X(30)
           VALUE 'EMS CONSUMER SESSION ENDED'.
       01  WS-COMMAREA.
           05  CA-STATE          PIC X VALUE 'S'.
       LINKAGE SECTION.
       01  DFHCOMMAREA.
           05  LK-STATE          PIC X.
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF EIBCALEN = 0
               PERFORM SEND-FRESH
           ELSE
               PERFORM RECEIVE-SCREEN
           END-IF
           EXEC CICS RETURN TRANSID('EMSC')
                COMMAREA(WS-COMMAREA) LENGTH(1)
           END-EXEC.

       SEND-FRESH.
           MOVE LOW-VALUES TO EMSMAPO
           PERFORM STAMP-CLOCK
           EXEC CICS SEND MAP('EMSMAP') MAPSET('EMSCON')
                FROM(EMSMAPO) ERASE
           END-EXEC.

       RECEIVE-SCREEN.
           EXEC CICS RECEIVE MAP('EMSMAP') MAPSET('EMSCON')
                INTO(EMSMAPI) RESP(WS-RESP)
           END-EXEC
           EVALUATE EIBAID
             WHEN DFHPF3
               EXEC CICS SEND TEXT FROM(WS-BYE) LENGTH(26) ERASE
               END-EXEC
               EXEC CICS RETURN END-EXEC
             WHEN DFHPF5
               MOVE SPACES TO MSGLNO
               PERFORM STAMP-CLOCK
               PERFORM SEND-PANEL
             WHEN DFHENTER
               PERFORM VALIDATE-PANEL
               PERFORM STAMP-CLOCK
               PERFORM SEND-PANEL
             WHEN OTHER
               MOVE 'INVALID KEY. PF3=EXIT, PF5=REFRESH' TO MSGLNO
               PERFORM STAMP-CLOCK
               PERFORM SEND-PANEL
           END-EVALUATE.

       VALIDATE-PANEL.
           IF SERVERI = SPACES OR SERVERI = LOW-VALUES
               MOVE 'SERVER IS REQUIRED' TO MSGLNO
               MOVE -1 TO SERVERL
           ELSE
             IF DESTI = SPACES OR DESTI = LOW-VALUES
               MOVE 'DESTINATION IS REQUIRED' TO MSGLNO
               MOVE -1 TO DESTL
             ELSE
               STRING 'MESSAGE SENT TO ' DELIMITED BY SIZE
                      DESTI DELIMITED BY SPACE
                      INTO MSGLNO
             END-IF
           END-IF.

       SEND-PANEL.
           EXEC CICS SEND MAP('EMSMAP') MAPSET('EMSCON')
                FROM(EMSMAPO) ERASE
           END-EXEC.

       STAMP-CLOCK.
           EXEC CICS ASKTIME ABSTIME(WS-ABSTIME) END-EXEC
           EXEC CICS FORMATTIME ABSTIME(WS-ABSTIME)
                MMDDYY(WS-DATE) DATESEP('/')
                TIME(WS-TIME) TIMESEP(':')
           END-EXEC
           MOVE WS-DATE TO SDATEO
           MOVE WS-TIME TO STIMEO.
