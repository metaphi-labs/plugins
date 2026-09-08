# playwright

A browser the model drives through `@playwright/mcp`: navigate, click, type, read the console and network, take screenshots it can see.

Needs Node 18 or newer. The first call downloads the server; the browser is your installed Chrome, or `npx playwright install chromium`.

`hum plugin install playwright@metaphi` (Humboldt) or `/plugin install playwright@metaphi` (Claude Code).

The server runs headless in a throwaway profile. Sites it may reach are the session's `allow_hosts` when the sandbox has a list.
