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

## Worked examples

Which chain answers which question:

| Question | Chain |
|---|---|
| Where are a character's skeleton / atlas / PNG? | `list_objects` → `get_object` → `get_spine_set` |
| What do this character's skills do? | `get_object` → `get_table` (skill templet) → `get_table` (string table) |
| Base stats and deployment cost? | `get_object`, or `get_table` on `LUA_UNIT_STAT_TEMPLET` |
| Which asset bundle does a field point at? | `find_asset_for_object` |
| What references this PNG on disk? | `find_related` |
| What does this field mean? | `search_fields` |

Every chain starts the same way, because a display name is not an identity:

```
counterside_list_objects(type="unit", query="Felix")
```

This returns ten rows. Only one is the playable SSR Felix — the rest are a
boss variant, a chibi ("Mini Felix") and skill-trophy units, all sharing the
display name. **Match on `strId`, never on `name`.** The playable one is
`id: 1278`, `strId: NKM_UNIT_REAPER_SA_COMMANDER`.

### Example 1 — "Find the skeleton, atlas, and PNG for this character"

```
User: Find the skeleton, atlas, and PNG files for Felix.
```

1. `counterside_list_objects(type="unit", query="Felix")` → take the row whose
   `strId` is `NKM_UNIT_REAPER_SA_COMMANDER`, `id` 1278.

2. `counterside_get_object(type="unit", id=1278)` → read the three Spine fields.
   They are separate characters, not one:
   - `m_SpriteBundleName` — `AB_UNIT_GAME_SPINE_...`, the live combat model
   - `m_SpineIllustName` — `AB_UNIT_ILLUST_...`, the Management illustration
   - `m_SpineSDName` — `AB_UNIT_SD_SPINE_...`, the chibi

3. `counterside_list_assets(path="Data/StreamingAssets", query="reaper_sa_commander")`
   → sixteen bundle folders. **Directory names are lowercase, file basenames are
   uppercase** — `ab_unit_game_spine_nkm_unit_reaper_sa_commander/` contains
   `UNIT_REAPER_SA_COMMANDER.skel`. Most rows are variants: `_summer` for the
   skin, `_silhouette`, and `_summon_*` for the Banshee Troopers and Chernobog.
   Match the bundle name against the field value exactly, not by prefix.

4. `counterside_get_spine_set(path="Data/StreamingAssets/ab_unit_game_spine_nkm_unit_reaper_sa_commander/TextAsset/UNIT_REAPER_SA_COMMANDER.skel")`
   → the three files tagged by role: `skeleton`, `atlas`, `texture`.

Repeat step 4 for the other two fields. The result:

| Spine | Skeleton | Atlas | Texture |
|---|---|---|---|
| combat | `UNIT_REAPER_SA_COMMANDER.skel` | `.atlas` | `.png` |
| illustration | `UNIT_ILLUST_REAPER_SA_COMMANDER.skel` | `.atlas` | `.png` |
| chibi | `UNIT_SD_REAPER_SA_COMMANDER.skel` | `.atlas` | `.png` |

**Do not use `find_asset_for_object` for this.** It resolves a field to its
bundle and returns whatever PNG it finds inside, which is not the atlas page —
for Felix it returns `NK_INK_01.png` for the combat field and
`ARIUS_LIQUID_024_SEQ.png` for the illustration field, both stray effect
textures, and an empty string for `m_SpriteName`. Use it to answer "which
bundle does this field point at"; use `get_spine_set` for the files inside it.

The character's title ("Red Witch") never appears in a filename. Asset names
key off the `strId`, so search the tree by that, not by the display name.

### Example 2 — "What do this character's skills do?"

```
User: What do Felix's skills do?
```

1. `counterside_get_object(type="unit", id=1278)` → `m_SkillStrID1` through
   `m_SkillStrID4` name the four slots in order: `_ATTACK` (basic), `_PASSIVE`,
   `_SKILL` (special), `_HYPER` (ultimate).

2. `counterside_get_table(directory="ab_script_unit_data", file="LUA_UNIT_SKILL_TEMPLET", query="REAPER_SA_COMMANDER")`
   → 20 rows: four skills × five levels. These carry the mechanics
   (`m_fCooltimeSecond`, `m_fEmpowerFactor`, `m_AttackCount`,
   `m_NKM_SKILL_TYPE`) and one `m_SkillDesc` string key per level.

3. `counterside_get_table(directory="ab_script_string_table", file="LUA_STRING_ENG", query="SI_UNIT_SKILL_DESC_REAPER_SA_COMMANDER")`
   → the English description text.

4. Skill names are a separate key family. Query
   `SI_UNIT_SKILL_NAME_REAPER_SA_COMMANDER` for "Navia Protocol", "Black Canal"
   and "Firepower Testing". A `_DESC_` query will not return them.

Three things that trip this up:

- **Descriptions are per-level.** Only Lv 1 and Lv 5 carry kit text; the middle
  levels are stat riders like `SI_UNIT_SKILL_DESC_HP@@5`. Query the whole
  `SI_UNIT_SKILL_DESC_REAPER_SA_COMMANDER` prefix to see which is which.
- **Read `LUA_STRING_ENG`.** The `LUA_SI_*_KOREA` tables return rows as
  `[key, value]` array pairs rather than objects, and their values are mojibake
  in the dump — the game applies its own decoding.
- **Some description strings carry control bytes** where the client injects
  markup, so "Blind" and "Stun" render as `Blindi]` and `Stuni]`. The word is
  what matters; the trailing token is formatting.

## Tests

```bash
.venv/bin/pytest -q                      # unit tests
.venv/bin/pytest -q -m parity            # parity vs Mod:Side (needs it running)
```

The parity tests compare this server's output against the live Node Mod:Side
API. They skip when it is not running, so the unit suite stays runnable
without Node. Override `CS_MODSIDE_API` when the launcher picks a port other
than `http://127.0.0.1:5175/mod-side/api`.
