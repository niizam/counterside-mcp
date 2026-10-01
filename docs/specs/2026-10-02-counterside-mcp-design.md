# CounterSide MCP Server — Design

Date: 2026-10-02
Status: Approved (design), pending spec review

## 1. Purpose

Build a standalone **Python MCP server** that lets an AI agent examine CounterSide
game data from local files: the decoded gameplay tables, the game objects
(units / ships / operators / gear) and the ids they reference, the extracted
asset tree (PNGs, Spine skeletons and atlases, audio, text assets), and the
curated "game systems" that organise all of it.

The capability target is **read parity with Mod:Side**
(`RevivalSide/server/assetViewer.js` + `RevivalSide/modules/asset-catalog` +
`RevivalSide/modules/gameplay-jsons`). An agent should be able to do, through
MCP tools, everything Mod:Side lets a human do in `?view=objects` and
`?view=assets` — and more, because MCP tools are programmable.

The server is **standalone**: it reads files directly and requires no Node
process, no `npm run modside`, and no running game listener.

## 2. Scope

### In scope

- Read-only inspection of gameplay tables, objects, assets, systems, and
  cross-references.
- Direct file access to the extracted-asset tree and the decoded table tree.
- Configurable roots (see §4) so the server can be pointed at any RevivalSide
  checkout or extracted-asset directory.

### Out of scope (explicitly)

- **Any write.** No mod project creation, no patches, no string tables, no
  asset replacement, no Unity AssetBundle compilation, no mod-runtime
  apply/rollback. There are no authoring tools in this server at all.
- No dependency on the Node engine, the launcher, the game listener, or
  Unity.
- No network access. Everything is local file I/O.

Read-only is a hard boundary, not a phase. Nothing in the architecture exists
to make writes easier later.

## 3. Background: how Mod:Side maps the data

Understanding these four layers is what makes the port tractable.

| Layer | Mod:Side implementation | What it does |
|---|---|---|
| Tables | `modules/gameplay-jsons/index.js` | Resolves decoded `LUA_*.json` gameplay tables under `<root>/[Assetbundles\|StreamingAssets]/<bundle>/luac/`. |
| Objects | `modules/asset-catalog/index.js` | Joins `LUA_UNIT_TEMPLET_BASE` / `LUA_ITEM_EQUIP_TEMPLET` with stat, skill, skin, collection tables; emits **id → asset-name mappings**. |
| Assets | `server/assetViewer.js` | Walks the extracted tree: directory listing with typed entries, file/range serving, text preview, Spine set resolution, related-data graph. |
| Systems | `GAME_SYSTEMS` in `assetViewer.js` | 26 curated game systems (units, items, stages, story, …) with keywords and "common edits" hints. |

Verified facts about the data on disk (this machine):

- The extracted-asset root (`…/AppData/Local/RevivalSide/extracted-assets`)
  holds **only art and audio**: ~49.5k PNG, ~9.3k JSON, ~3.4k `.skel`,
  ~3.4k `.atlas`, ~2.1k WAV. It contains **no decoded gameplay tables**.
- The decoded tables live in the **repo** at
  `RevivalSide/gameplay-jsons/[StreamingAssets|Assetbundles]/<bundle>/luac/LUA_*.json`.
- The object→asset join is real: a unit record's `m_InvenIconName`
  (`AB_INVEN_ICON_NKM_SHIP_A_COFFIN`) resolves to
  `Data/StreamingAssets/ab_inven_icon_unit/Texture2D/AB_INVEN_ICON_NKM_SHIP_A_COFFIN.png`.
- This extract has **no `ObjectIndex/objects.json`**, so Mod:Side's Unity
  object-reference path is inactive. The related graph falls back to the
  name/index path, which the port follows.

Consequence: **objects need two roots**, not one — the table root for records
and the asset root for art. The health tool reports both so a misconfiguration
is diagnosable rather than mysterious.

## 4. Configuration

The server resolves four roots. Because the asset tree and the table tree can
live in different places (often on different machines or WSL/Windows
boundaries), **every root is independently overridable by environment
variable**.

### 4.1 Base root

`CS_REVIVALSIDE_ROOT` points at a RevivalSide checkout or install directory.
All other roots default to locations inside it.

Resolution order when the variable is unset:

1. `CS_REVIVALSIDE_ROOT` if set and the directory exists.
2. The sibling `RevivalSide/` directory next to this package
   (i.e. `<parent of counterside-mcp>/RevivalSide`).
3. Fail fast at startup with a message naming the variable and the paths tried.

### 4.2 Root table

| Root | Environment variable | Default (relative to base root) | Contents |
|---|---|---|---|
| Asset root | `CS_ASSET_VIEWER_ROOT` | `extracted-assets/all`, else `extracted-assets` | PNG / WAV / Spine / text asset tree |
| Table root | `CS_GAMEPLAY_TABLES_DIR` | `gameplay-jsons` | decoded `LUA_*.json` under `<bundle>/luac/` |
| Wiki data | `CS_COUNTERSIDE_WIKI` | `wiki/data` | `idIndex.json`, `units.json`, `gears.json` |
| Server data | `CS_SERVER_DATA_DIR` | `server-data` | `units.json` authoritative roster |

Additional table roots may be appended with `CS_GAMEPLAY_JSON_ROOTS` and
`CS_GAMEPLAY_TABLE_ROOTS` (comma- or path-delimited, matching the existing
repo convention), searched in order after `CS_GAMEPLAY_TABLES_DIR`.

Environment variable names are chosen to match the ones the RevivalSide repo
already uses (`CS_ASSET_VIEWER_ROOT`, `CS_GAMEPLAY_TABLES_DIR`,
`CS_GAMEPLAY_JSON_ROOTS`) so a launcher that already sets them for Mod:Side
configures this server too.

### 4.3 Root expansion and precedence

For both the asset root and each table root, both layouts are always tried —
`<root>/Assetbundles` and `<root>/StreamingAssets` — exactly as Mod:Side's
`expandTableRoots` does. A root that already ends in one of those two names is
used directly.

Precedence, highest first:

1. Tool-call argument (where a tool accepts an explicit root).
2. `CS_ASSET_VIEWER_ROOT` / `CS_GAMEPLAY_TABLES_DIR` (+ `_ROOTS` extras).
3. Default derived from `CS_REVIVALSIDE_ROOT`.
4. Auto-discovered sibling `RevivalSide/`.
5. Error.

`counterside_health` reports the resolved value of each root, and whether each
exists and is readable.

### 4.4 Path safety

Every caller-supplied asset path is normalised (backslashes to POSIX, `.`/`..`
collapsed) and then checked to be inside the resolved asset root before any
file operation. A path that escapes the root is rejected with a tool error.
This is parity with Mod:Side's `resolveExistingAssetPath` / `isInside`, and it
means an agent cannot be steered outside the tree.

## 5. Module layout

```
counterside-mcp/
  pyproject.toml                 # deps: mcp; dev: pytest
  README.md                      # setup + client configuration
  src/counterside_mcp/
    __init__.py
    server.py                    # MCPServer instance, lifespan, tool/resource registration
    config.py                    # root resolution, env handling, health
    errors.py                    # domain errors → ToolError
    paths.py                     # normalize, resolve, is_inside, containment
    tables.py                    # table roots, listing, read, extract_records, field schema
    systems.py                   # GAME_SYSTEMS data + search/ranking
    objects.py                   # asset-catalog port (unit/ship/operator/gear)
    assets.py                    # directory listing, file info, text, spine set, related
    stats.py                     # NKM_STAT_TYPE, statTypeValue, assetTypeFor, humanize
    models.py                    # dataclasses for result shapes
  tests/
    unit/                        # one module per ported pure function
    parity/                      # optional golden diffs vs the Node API
    fixtures/                    # tiny synthetic trees + recorded golden JSON
```

All ported logic lives in plain functions that take resolved roots and return
data. `server.py` only registers those functions as MCP tools and resources.
This keeps every ported behaviour unit-testable without an MCP client.

## 6. Tool and resource surface

Thirteen tools in four groups, plus four resource templates. Every tool is
read-only.

### 6.1 Discovery

| Tool | Arguments | Returns |
|---|---|---|
| `counterside_health` | — | Resolved roots, existence/readability of each, table count, asset-tree availability, systems count, package version. |
| `counterside_list_systems` | — | The 26 game systems: `id`, `title`, `description`, `keywords`, `tableCount`, `commonEdits[]`. |
| `counterside_search_fields` | `query` (≥2 chars) | Ranked systems, tables and fields matching the query, mirroring Mod:Side's field search and `FIELD_ALIASES`. |

### 6.2 Tables

| Tool | Arguments | Returns |
|---|---|---|
| `counterside_list_tables` | `query?`, `offset?`, `limit?` | Table entries (`directory`, `fileName`, `tableName`, `relativePath`, `searchText`), paginated. |
| `counterside_get_table` | `directory`, `file`, `query?`, `offset?`, `limit?` | Decoded records, `unfilteredTotal`, `total`, `recordIndexes`, and the table entry. |

### 6.3 Objects

Object types: `unit`, `ship`, `operator`, `gear`.

| Tool | Arguments | Returns |
|---|---|---|
| `counterside_list_objects` | `type?`, `query?`, `offset?`, `limit?` | Summaries: `id`, `strId`, `name`, `image`, `meta`. |
| `counterside_get_object` | `type`, `id` | Full inspection: identity ids, every referenced id with `field`, `description`, `sourceTable` and `preview` (resolved asset path), unit stats (base + per level) or gear stat ranges, plus skill / skin / collection / ship-build / operator-passive links. |

`get_object` is the heart of the object↔asset mapping: each asset-bearing field
(`m_InvenIconName`, `m_FaceCardName`, `m_SpineIllustName`, `m_SpineSDName`,
`m_MiniMapFaceName`, `m_SpriteBundleName`, `m_ItemEquipIconName`,
`m_UnitSkillIcon`, …) is resolved against the asset root and returned as a real
relative path, or empty when not present in this extract.

### 6.4 Assets

| Tool | Arguments | Returns |
|---|---|---|
| `counterside_list_assets` | `path?`, `query?`, `offset?`, `limit?` | Directory entries: `name`, `path`, `kind`, and for files `extension`, `size`, `assetType`. Directories first, then files, each name-sorted. |
| `counterside_get_asset` | `path` | For images (PNG/JPEG/WEBP): the image itself as MCP `Image` content, so the agent sees it. For other files: metadata (`path`, `size`, `extension`, `assetType`, `contentType`). |
| `counterside_read_text` | `path`, `maxBytes?` | Text preview for `.atlas/.bytes/.csv/.json/.log/.lua/.md/.txt/.xml/.yaml/.yml`, capped (default 512 KiB), with `truncated` flag. |
| `counterside_get_spine_set` | `path` | For a `.skel`/`.atlas`/`.json`/`.bytes` Spine source: the matched set — skeleton file(s), atlas, and texture pages — each with `path`, `name`, `role`; or `ready:false` with `missing[]` naming exactly what could not be resolved. |
| `counterside_find_related` | `path` | Files sharing the Unity asset name, Unity object references, and gameplay-table rows whose id/strId/name/image matches the asset or its JSON contents. |
| `counterside_find_asset_for_object` | `type`, `id`, `field?` | Convenience join: object asset field(s) → resolved asset path(s). With `field`, checks only that field. |

### 6.5 Resources

Cheap, cache-friendly reads for clients that prefer resources over tools:

- `counterside://systems`
- `counterside://table/{directory}/{file}`
- `counterside://object/{type}/{id}`
- `counterside://asset/{+path}` (text resources; binary stays a tool result)

## 7. Behavioural parity notes

Details that must match Mod:Side, each of which gets a unit test:

- **Table name normalisation** — `normalizeTableBaseName` strips repeated
  `.json/.luac/.lua/.bytes` suffixes.
- **Record extraction** — `extractTableRecords` handles a bare array,
  `{records:[]}`, `{root:[]}`, and a keyed `root` object (becoming
  `{__key, ...entry}`).
- **Table preference** — `.json` beats `.luac` when both exist for a table.
- **Table directory discovery** — walks roots for files under a `luac/`
  segment; the segment must not be first or last.
- **Asset typing** — `assetTypeFor`: `.png`→Image, `.wav`→Audio,
  `.skel`→Spine skeleton, `.atlas`→Spine atlas, `.bytes`→TextAsset bytes,
  `TypeTree/<T>`→`Unity <T>`, `<T>Meta`→`Unity <T> metadata`, `ObjectIndex`,
  else the uppercased extension.
- **Stat ids** — `statTypeValue` against the `NKM_STAT_TYPE` enum (numeric
  passthrough, then name lookup, else 0).
- **Related-value normalisation** — `normalizeRelationValue`: NFKC, lowercase,
  strip everything but letters and digits.
- **Object type normalisation** — unknown type is an error, default `unit`.
- **Pagination** — default limit 100, clamped to 250.
- **Spine detection** — `.skel` always; `.json`/`.bytes` only when the parsed
  document has `skeleton` plus `bones`/`slots`/`animations`.
- **Atlas page parsing** — lines that are not `key: value` and end in `.png`.

The 26-system table and the stat enum are data, not behaviour. They are copied
verbatim from the Node source and pinned by parity tests.

## 8. Error handling

- A domain error type carries a message; `server.py` maps it to an MCP
  `ToolError` with a short, actionable message.
- Missing path, unknown object id, unknown object type, path escaping the root,
  undecodable table, and non-text file each produce a distinct message.
- `health` never throws: it reports what is missing so a misconfigured root is
  visible before the agent starts guessing.

## 9. Testing

Two layers.

**Unit tests** (`tests/unit/`) cover every ported pure function with
hand-derived expectations and synthetic fixtures: `extractTableRecords`,
`normalizeTableBaseName`, `parseGameplayTableFilePath`, `assetTypeFor`,
`statTypeValue`, `humanize`, `normalizeRelationValue`, atlas page parsing,
Spine-source detection, object type normalisation, path containment, and the
table/root precedence rules.

**Parity harness** (`tests/parity/`, marked `@pytest.mark.parity`) records a
fixture set of calls and compares Python output against the Node API when
`npm run modside` is reachable; the JSON is diffed, ignoring volatile fields.
When the server is not running the tests skip cleanly, so the suite is always
green in a bare checkout. This is the mechanism that catches drift in the
26-system table, the stat enum, and the object join.

An end-to-end smoke test drives the MCP server in-process with the MCP client
and asserts that `health`, one table read, one object inspection and one asset
listing all succeed against a synthetic fixture tree.

## 10. Risks

| Risk | Mitigation |
|---|---|
| Stat enum or system table drifts from Node | Parity tests pin both; they are data, copied verbatim. |
| `idIndex.json` is ~53 MB | Loaded lazily, only for `find_related` and references; never at startup. |
| Asset root and table root are in different places | Independent env vars; `health` reports each resolved root and its existence. |
| Mod:Side's `ObjectIndex` path is inactive in this extract | Port follows the name/index fallback; `find_related` still returns same-name files and table matches. |
| Manifest JSON contains Windows absolute paths | Not used for path resolution this phase; if surfaced, normalised to POSIX and treated as metadata only. |
| Spine sets with multiple skeletons/atlases | Mirror Mod:Side's base-name matching and report unresolved parts in `missing[]` rather than guessing. |

## 11. Milestones

1. **Skeleton** — package, config/root resolution, `health`, MCP registration,
   smoke test.
2. **Tables** — table discovery, listing, reading, record extraction, field
   schema, search.
3. **Systems** — the curated system table and keyword ranking.
4. **Objects** — unit/ship/operator/gear listing and the full inspection join,
   including asset-preview resolution.
5. **Assets** — directory listing, file info/image, text preview, Spine set,
   related graph.
6. **Parity** — golden fixtures and the optional Node diff harness.

Each milestone is independently verifiable and leaves the server usable.
