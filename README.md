# Plugins

Plugins for Hum, in Hum's own layout.

```
hum plugin marketplace add metaphi-labs/plugins
hum plugin install pyright-lsp@metaphi
```

## Layout

```
.hum-plugin/marketplace.json            the catalog
plugins/<name>/                         one plugin per directory
plugins/<name>/.hum-plugin/plugin.json  its manifest
```

`${HUM_PLUGIN_ROOT}` in a plugin's files names the plugin's own directory.

## Contribute

Open a pull request adding a directory under plugins/ and an entry in the catalog. A plugin's hooks, tool servers and language servers run on the person's machine, so every entry is reviewed before it lands.
