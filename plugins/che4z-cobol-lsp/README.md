# che4z-cobol-lsp

COBOL code intelligence through Broadcom's [COBOL Language Support](https://github.com/eclipse-che4z/che-che4z-lsp-for-cobol) (Eclipse Che4z, EPL-2.0): a full Enterprise COBOL parser with copybooks, CICS, DB2 and Datacom SQL, and the IDMS and DaCo dialects.

Install the engine, then the plugin:

```
hum plugin marketplace add metaphi-labs/plugins
hum plugin install che4z-cobol-lsp@metaphi
~/.hum/plugins/installed/metaphi/che4z-cobol-lsp/bin/che4z-install
```

`che4z-install` fetches the release package for this machine from GitHub into `~/.che4z`: a native engine on macOS and Linux, `server.jar` for a Java 8 runtime elsewhere. `CHE4Z_HOME` moves the directory, `CHE4Z_VERSION` picks a release.

`bin/che4z-cobol-lsp` starts the engine behind `server/proxy.py` (python3), which answers the engine's own client requests: where a copybook is (`copybook/resolve`) and what it holds (`file/content`). Everything else passes through as plain LSP.

## Copybooks

The engine looks for copybooks in `Copybooks`, `CPY` and `copy` (any case) at the workspace root and one level down. Another layout goes in the plugin's `.lsp.json` under `cobol-lsp.cpy-manager.paths-local`, or in your own `[[lsp]]` table:

```toml
[[lsp]]
name = "che4z-cobol"
command = "che4z-cobol-lsp"
extensions = [".cbl", ".cpy"]
[lsp.settings.cobol-lsp.cpy-manager]
paths-local = ["src/copybooks"]
```

Settings the engine reads: `cobol-lsp.cpy-manager.paths-local`, `cobol-lsp.dialects`, `cobol-lsp.target-sql-backend` (`DB2_SERVER`, the default, or `DATACOM_SERVER`).
