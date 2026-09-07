# Plugins

Plugins for Humboldt, in the layout Claude Code reads too.

```
hum plugin marketplace add metaphi-labs/plugins
hum plugin install pyright-lsp@metaphi
```

## Layout

```
.claude-plugin/marketplace.json   the catalog
plugins/<name>/                   one plugin per directory
```

## Contribute

Open a pull request adding a directory under plugins/ and an entry in the catalog. A plugin's hooks, tool servers and language servers run on the person's machine, so every entry is reviewed before it lands.
