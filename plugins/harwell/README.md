# harwell plugin

Skills for building on the mainframe through the Harwell emulator. Install it and every session on a mainframe estate loads the shop's rules on demand.

```
hum plugin marketplace add metaphi-labs/plugins
hum plugin install harwell@metaphi
```

| Skill | What it carries |
|---|---|
| `cics-screens` | The online screen: BMS macro source in HLASM's columns, the panel standard with one worked example, the pseudo-conversational program, the case and the oracle that prove it on the emulator. |

The emulator itself arrives as the `harwell` tool server: managed on a Metaphi AI deployment, or added with `hum mcp add harwell https://harwell.metaphi.ai/mcp/` and a key.

Each skill ships its cases under `cases/`; `hum skill eval cics-screens` runs them.
