# counterside-mcp

A read-only MCP server that lets an AI agent examine CounterSide game data:
decoded gameplay tables, game objects (units / ships / operators / gear) and
the ids they reference, and the extracted asset tree (PNGs, Spine, audio,
text).

It reads local files directly. No Node process, no game listener, no network,
and **no writes** — every tool is read-only.

## Install

Requires Python 3.10 or newer.

```bash
cd counterside-mcp
python3 -m venv .venv
.venv/bin/pip install -e .
```

## Configure

Point the server at your RevivalSide directory:

```bash
export CS_REVIVALSIDE_ROOT=/path/to/RevivalSide
```

Each root can also be set individually, which is useful when the tables and
the extracted assets live in different places — a source checkout holds
`gameplay-jsons`, while the installed game holds `extracted-assets`:

| Variable | Default | Contents |
|---|---|---|
| `CS_REVIVALSIDE_ROOT` | sibling `RevivalSide/` | base for all defaults below |
| `CS_ASSET_VIEWER_ROOT` | `<base>/extracted-assets/all` | PNG / WAV / Spine / text |
| `CS_GAMEPLAY_TABLES_DIR` | `<base>/gameplay-jsons` | decoded `LUA_*.json` tables |
| `CS_GAMEPLAY_JSON_ROOTS` | _(none)_ | extra table roots, comma- or semicolon-separated |
| `CS_GAMEPLAY_TABLE_ROOTS` | _(none)_ | extra table roots, comma- or semicolon-separated |
| `CS_COUNTERSIDE_WIKI` | `<base>/wiki/data` | the data dir holding `idIndex.json` |
| `CS_SERVER_DATA_DIR` | `<base>/server-data` | authoritative `units.json` |

A few details that are easy to get wrong:

- **The asset root is the directory above the bundles**, normally
  `.../extracted-assets/all`. Pointing at `extracted-assets` itself still
  works only when there is no `all` subdirectory.
- Each table root expands to its `Assetbundles` **and** `StreamingAssets`
  subdirectories, unless the path you gave already ends in one of those names.
- All three table variables are combined into one root list. The built-in
  `<base>/gameplay-jsons` default applies only when none of them is set, so
  setting `CS_GAMEPLAY_JSON_ROOTS` alone does not also give you
  `gameplay-jsons` — list it too if you want both.
- `CS_COUNTERSIDE_WIKI` is the data directory itself (`.../wiki/data`), not
  the `wiki` directory above it. The 55 MB `idIndex.json` is read from there,
  never rebuilt.

Call `counterside_health` first: it reports every resolved root and whether it
exists, so a misconfiguration is visible immediately.

## Client configuration

```json
{
  "mcpServers": {
    "counterside": {
      "command": "/path/to/counterside-mcp/.venv/bin/counterside-mcp",
      "env": { "CS_REVIVALSIDE_ROOT": "/path/to/RevivalSide" }
    }
  }
}
```

Add `CS_ASSET_VIEWER_ROOT` to `env` when the extracted assets are installed
somewhere other than the RevivalSide directory.

## Tools

- **Discovery** — `counterside_health`, `counterside_list_systems`, `counterside_search_fields`
- **Tables** — `counterside_list_tables`, `counterside_get_table`
- **Objects** — `counterside_list_objects`, `counterside_get_object`, `counterside_find_asset_for_object`
- **Assets** — `counterside_list_assets`, `counterside_get_asset`, `counterside_read_text`, `counterside_get_spine_set`, `counterside_find_related`

`counterside_get_asset` returns the image itself for PNG and JPEG files, so an
agent can look at a sprite instead of guessing from its name.
`counterside_find_related` is the bridge back from an image on disk to the
gameplay tables that reference it.

## Tests

```bash
.venv/bin/pytest -q                      # unit tests
.venv/bin/pytest -q -m parity            # parity vs Mod:Side (needs it running)
```

The parity tests compare this server's output against the live Node Mod:Side
API. They skip when it is not running, so the unit suite stays runnable
without Node. Override `CS_MODSIDE_API` when the launcher picks a port other
than `http://127.0.0.1:5175/mod-side/api`.
