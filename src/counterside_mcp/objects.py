"""Game objects: units, ships, operators and gear.

A faithful port of Mod:Side's ``modules/asset-catalog``: the same tables, the
same joins, and the same asset-preview rules, so an agent reading through this
server sees what the UI shows.
"""

import json
import re
from functools import lru_cache
from pathlib import Path

from .config import Roots
from .errors import DomainError
from .stats import humanize, stat_type_value
from .tables import read_table_records

TYPES = {"unit", "ship", "operator", "gear"}

SKILL_TABLE = {
    "unit": ("LUA_UNIT_SKILL_TEMPLET.json", "m_UnitSkillID", "m_UnitSkillIcon"),
    "ship": ("LUA_SHIP_SKILL_TEMPLET.json", "m_ShipSkillID", "m_ShipSkillIcon"),
    "operator": ("LUA_OPERATOR_SKILL_TEMPLET.json", "m_OperSkillID", "m_OperSkillIcon"),
}

UNIT_ASSETS = [
    ("m_InvenIconName", "Management/list icon PNG ID", "Loaded from AB_INVEN_ICON_UNIT for Management roster slots, deck slots, rewards, and other compact unit icons."),
    ("m_FaceCardName", "Recruitment/card PNG ID", "Loaded from AB_UNIT_FACE_CARD for recruitment banners, gacha cards, deck ship cards, and other large card portraits."),
    ("m_SpineIllustName", "Management/gacha illustration ID", "Large animated Spine illustration used by Management details, collection profiles, recruitment banners, and character showcases."),
    ("m_SpineSDName", "SD/chibi illustration ID", "Small Spine illustration used by office, collection, and event views that request the SD presentation."),
    ("m_MiniMapFaceName", "Battle minimap portrait ID", "Portrait loaded from AB_UNIT_MINI_MAP_FACE for battle, dive, and warfare minimaps."),
    ("m_SpriteBundleName", "Battle Spine bundle ID", "AssetBundle containing the live combat Spine object."),
    ("m_SpriteName", "Battle Spine object ID", "Object name opened from m_SpriteBundleName for the live combat model and animations."),
]

# Asset-bearing fields find_asset_for_object can report on.
ASSET_FIELDS = [field for field, _, _ in UNIT_ASSETS] + ["m_ItemEquipIconName"]

_UNIT_SOURCE_FILES = [
    ("LUA_UNIT_TEMPLET_BASE.json", "LUA_UNIT_STAT_TEMPLET.json"),
    ("LUA_UNIT_TEMPLET_BASE2.json", "LUA_UNIT_STAT_TEMPLET2.json"),
    ("LUA_UNIT_TEMPLET_BASE_SD.json", "LUA_UNIT_STAT_TEMPLET_SD.json"),
    ("LUA_UNIT_TEMPLET_BASE_OPR.json", "LUA_UNIT_STAT_TEMPLET_OPR.json"),
]

_SAFE_ASSET_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
_STAT_RATE_FIELD = re.compile(r"StatRate$")
_RATE_FACTOR = {
    "NST_HP": "NST_HP_FACTOR",
    "NST_ATK": "NST_ATK_FACTOR",
    "NST_DEF": "NST_DEF_FACTOR",
    "NST_CRITICAL": "NST_CRITICAL_FACTOR",
    "NST_HIT": "NST_HIT_FACTOR",
    "NST_EVADE": "NST_EVADE_FACTOR",
}


def normalize_object_type(value) -> str:
    """The Node catalog's normalizeType: default to 'unit', reject the rest."""
    object_type = str(value or "unit").lower()
    if object_type not in TYPES:
        raise DomainError(f"Unknown object type: {object_type}")
    return object_type


# --------------------------------------------------------------------------
# Small helpers mirroring the Node ones.
# --------------------------------------------------------------------------


def _number_or_none(value):
    """JS Number(value), narrowed to a finite number or None.

    Booleans are excluded: ``Number(true)`` is 1 in JS but a boolean field here
    is never a quantity, and treating one as a number would invent a value.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return 0
    try:
        number = float(text)
    except ValueError:
        return None
    return int(number) if number.is_integer() else number


def _object_id(object_type: str, record: dict) -> int:
    field = "m_ItemEquipID" if object_type == "gear" else "m_UnitID"
    return int(_number_or_none(record.get(field)) or 0)


def _group_by(rows: list, field: str) -> dict[str, list]:
    grouped: dict[str, list] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = row.get(field)
        if key is None or key == "":
            continue
        grouped.setdefault(str(key), []).append(row)
    return grouped


def _index_by(rows: list, field: str) -> dict[str, dict]:
    indexed: dict[str, dict] = {}
    for row in rows:
        if isinstance(row, dict) and row.get(field) is not None:
            indexed.setdefault(str(row[field]), row)
    return indexed


def _unique_by(rows: list, field: str) -> list[dict]:
    seen: set[str] = set()
    kept = []
    for row in rows:
        value = row.get(field) if isinstance(row, dict) else None
        if value is None or str(value) in seen:
            continue
        seen.add(str(value))
        kept.append(row)
    return kept


def _array_value(value) -> list:
    if isinstance(value, list):
        return value
    return [] if value is None or value == "" else [value]


def _first_present(*values):
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _first_field(record: dict, fields: list[str]) -> str:
    for field in fields:
        if record.get(field) is not None and record.get(field) != "":
            return field
    return ""


def _normalize_rate_stat(stat_type, row: dict) -> str:
    """A row whose range lives in a ``*StatRate`` field is a percentage stat."""
    text = str(stat_type or "")
    if not any(_STAT_RATE_FIELD.search(key) for key in (row or {})):
        return text
    return _RATE_FACTOR.get(text, text)


# --------------------------------------------------------------------------
# Table loading
# --------------------------------------------------------------------------


def _read_rows(roots: Roots, directory: str, file_name: str) -> list[dict]:
    records, _ = read_table_records(roots, directory, file_name)
    return [row for row in records if isinstance(row, dict)]


@lru_cache(maxsize=8)
def _load_units(roots: Roots) -> list[dict]:
    """The units.json roster when present, else the four base/stat file pairs.

    Cached per root set: inspection and listing both need it, and re-reading the
    base/stat pair for every call would repeat the same few megabytes of JSON.
    Callers treat the result as immutable.
    """
    stored_path = Path(roots.server_data_dir) / "units.json"
    try:
        stored = json.loads(stored_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        stored = None
    if isinstance(stored, dict) and isinstance(stored.get("byId"), dict):
        return [row for row in stored["byId"].values() if isinstance(row, dict)]

    by_id: dict[int, dict] = {}
    for base_file, stat_file in _UNIT_SOURCE_FILES:
        base = _read_rows(roots, "ab_script_unit_data", base_file)
        stats = _index_by(_read_rows(roots, "ab_script_unit_data", stat_file), "m_UnitStrID")
        for row in base:
            unit_id = int(_number_or_none(row.get("m_UnitID")) or 0)
            if unit_id <= 0:
                continue
            by_id[unit_id] = {
                **row,
                "_sourceTable": base_file,
                "_stat": stats.get(str(row.get("m_UnitStrID"))),
            }
    return list(by_id.values())


class Catalog:
    """The object tables and their joins.

    Each grouping loads on first use: listing units should not pay for the
    skill, skin and set-option tables that only inspection reads.
    """

    def __init__(self, roots: Roots):
        self._roots = roots
        self._loaded: dict[str, object] = {}

    def _get(self, key: str, loader):
        if key not in self._loaded:
            self._loaded[key] = loader()
        return self._loaded[key]

    def _units(self) -> list[dict]:
        def load():
            units = _load_units(self._roots)
            for unit in units:
                unit.setdefault("_sourceTable", "LUA_UNIT_TEMPLET_BASE.json")
            # Node sorts every collection by its numeric identity.
            units.sort(key=lambda row: _object_id("unit", row))
            return units

        return self._get("units", load)

    def _units_of_type(self, unit_type: str) -> list[dict]:
        if unit_type == "unit":
            excluded = ("NUT_SHIP", "NUT_OPERATOR", "NUT_SYSTEM")
            return [
                row for row in self._units()
                if str(row.get("m_NKM_UNIT_TYPE") or "") not in excluded
            ]
        return [row for row in self._units() if str(row.get("m_NKM_UNIT_TYPE") or "") == unit_type]

    def _gear(self) -> list[dict]:
        def load():
            rows = _read_rows(self._roots, "ab_script_item_templet", "LUA_ITEM_EQUIP_TEMPLET.json")
            rows.sort(key=lambda row: _object_id("gear", row))
            return rows

        return self._get("gear", load)

    def _wiki(self, kind: str) -> dict[str, dict]:
        return self._get(
            f"wiki_{kind}", lambda: _read_wiki_index(Path(self._roots.wiki_dir) / f"{kind}.json")
        )

    def _grouped(self, key: str, directory: str, file_name: str, field: str) -> dict[str, list]:
        return self._get(
            key, lambda: _group_by(_read_rows(self._roots, directory, file_name), field)
        )

    def _indexed(self, key: str, directory: str, file_name: str, field: str) -> dict[str, dict]:
        return self._get(
            key, lambda: _index_by(_read_rows(self._roots, directory, file_name), field)
        )

    def records(self, object_type: str) -> list[dict]:
        if object_type == "gear":
            return self._gear()
        if object_type == "ship":
            return self._units_of_type("NUT_SHIP")
        if object_type == "operator":
            return self._units_of_type("NUT_OPERATOR")
        return self._units_of_type("unit")

    @property
    def wiki_units(self) -> dict[str, dict]:
        return self._wiki("units")

    @property
    def wiki_gears(self) -> dict[str, dict]:
        return self._wiki("gears")

    @property
    def unit_skills(self) -> dict[str, list]:
        return self._grouped("unit_skills", "ab_script_unit_data", "LUA_UNIT_SKILL_TEMPLET.json", "m_UnitSkillStrID")

    @property
    def ship_skills(self) -> dict[str, list]:
        return self._grouped("ship_skills", "ab_script", "LUA_SHIP_SKILL_TEMPLET.json", "m_ShipSkillStrID")

    @property
    def operator_skills_by_str(self) -> dict[str, list]:
        return self._grouped("opr_skills_str", "ab_script_unit_data", "LUA_OPERATOR_SKILL_TEMPLET.json", "m_OperSkillStrID")

    @property
    def operator_skills_by_id(self) -> dict[str, list]:
        return self._grouped("opr_skills_id", "ab_script_unit_data", "LUA_OPERATOR_SKILL_TEMPLET.json", "m_OperSkillID")

    @property
    def operator_passives(self) -> dict[str, list]:
        return self._grouped("opr_passives", "ab_script_unit_data", "LUA_OPERATOR_RANDOM_PASSIVE_TEMPLET.json", "m_OprPassiveGroupID")

    @property
    def skins(self) -> dict[str, list]:
        return self._grouped("skins", "ab_script", "LUA_SKIN_TEMPLET.json", "m_SkinEquipUnitID")

    @property
    def collections(self) -> dict[str, list]:
        return self._grouped("collections", "ab_script", "LUA_COLLECTION_UNIT_TEMPLET.json", "m_UnitID")

    @property
    def ship_builds(self) -> dict[str, list]:
        return self._grouped("ship_builds", "ab_script", "LUA_SHIP_BUILD_TEMPLET.json", "m_ShipID")

    @property
    def random_stats(self) -> dict[str, list]:
        return self._grouped("random_stats", "ab_script", "LUA_ITEM_EQUIP_RANDOM_STAT.json", "m_StatGroupID")

    @property
    def potentials(self) -> dict[str, list]:
        return self._grouped("potentials", "ab_script", "LUA_ITEM_EQUIP_POTENTIAL_OPTION.json", "m_PotentialOptionGroupID")

    @property
    def set_options(self) -> dict[str, dict]:
        return self._indexed("set_options", "ab_script_item_templet", "LUA_ITEM_EQUIP_SET_OPTION.json", "m_EquipSetID")

    @property
    def stat_info(self) -> dict[str, dict]:
        return self._indexed("stat_info", "ab_script", "LUA_STAT_INFO_TEMPLET.json", "Stat_ID")


def _read_wiki_index(path: Path) -> dict[str, dict]:
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return _index_by(rows if isinstance(rows, list) else [], "id")


# --------------------------------------------------------------------------
# Summaries and inspection
# --------------------------------------------------------------------------


def _stat_name(stat_type, catalog: Catalog) -> str:
    base = str(stat_type or "").removesuffix("_FACTOR")
    info = catalog.stat_info.get(base, {})
    return humanize(info.get("Stat_ID") or base)


def summarize(catalog: Catalog, object_type: str, record: dict) -> dict:
    object_id = _object_id(object_type, record)
    is_gear = object_type == "gear"
    wiki = (catalog.wiki_gears if is_gear else catalog.wiki_units).get(str(object_id), {})
    str_id = record.get("m_ItemEquipStrID") if is_gear else record.get("m_UnitStrID")
    raw_name = record.get("m_ItemEquipName") if is_gear else record.get("m_Name")
    if is_gear:
        parts = [
            record.get("m_NKM_ITEM_GRADE"),
            f"T{record.get('m_NKM_ITEM_TIER') or '?'}",
            record.get("m_ItemEquipPosition"),
            record.get("m_EquipUnitStyleType"),
        ]
    else:
        parts = [
            record.get("m_NKM_UNIT_GRADE"),
            record.get("m_NKM_UNIT_STYLE_TYPE"),
            record.get("m_NKM_UNIT_ROLE_TYPE"),
            "Monster" if record.get("m_bMonster") else "",
        ]
    return {
        "type": object_type,
        "id": object_id,
        "strId": str(str_id or ""),
        "name": str(wiki.get("name") or raw_name or str_id or f"{object_type} {object_id}"),
        "image": str(wiki.get("image") or ""),
        "meta": " | ".join(str(part) for part in parts if part),
    }


def _asset_preview(roots: Roots, field: str, value) -> str:
    """Resolve an asset-bearing field to a real relative path, or ''.

    Ported from the Node ``assetPreview``: a fixed candidate list for the icon
    fields, then a directory scan by lowercased name for the Spine bundles.
    """
    if not value or not _SAFE_ASSET_NAME.match(str(value)):
        return ""
    if field == "m_UnitSkillIcon":
        candidates = [
            f"Data/StreamingAssets/ab_ui_unit_skill_icon/Sprite/{value}.png",
            f"Assetbundles/ab_ui_unit_skill_icon/Sprite/{value}.png",
        ]
    elif field == "m_InvenIconName":
        candidates = [f"Data/StreamingAssets/ab_inven_icon_unit/Texture2D/{value}.png"]
    elif field == "m_FaceCardName":
        candidates = [
            f"Data/StreamingAssets/ab_unit_face_card_loc/Texture2D/{value}.png",
            f"Data/StreamingAssets/ab_unit_face_card/Texture2D/{value}.png",
        ]
    elif field == "m_MiniMapFaceName":
        candidates = [f"Data/StreamingAssets/ab_unit_mini_map_face/Texture2D/{value}.png"]
    elif field == "m_ItemEquipIconName":
        # The shipped game names gear icons AB_INVEN_ICON_IQI_EQUIP_<value>.png,
        # which matches no candidate in the upstream catalog, so every gear icon
        # preview comes back empty there. The real prefix leads here; the two
        # upstream spellings stay as fallbacks for other builds.
        candidates = [
            f"Data/StreamingAssets/ab_inven_icon_item_equip/Texture2D/AB_INVEN_ICON_IQI_EQUIP_{value}.png",
            f"Data/StreamingAssets/ab_inven_icon_item_equip/Texture2D/AB_INVEN_ICON_{value}.png",
            f"Data/StreamingAssets/ab_inven_icon_item_equip/Texture2D/{value}.png",
        ]
    else:
        candidates = []
    for relative in candidates:
        if any((Path(root) / relative).exists() for root in roots.asset_dirs):
            return relative
    if field not in ("m_SpineIllustName", "m_SpineSDName", "m_SpriteBundleName"):
        return ""
    for prefix in ("Data/StreamingAssets", "Assetbundles"):
        relative_dir = f"{prefix}/{str(value).lower()}/Texture2D"
        for root in roots.asset_dirs:
            directory = Path(root) / relative_dir
            try:
                images = sorted(
                    entry.name
                    for entry in directory.iterdir()
                    if re.search(r"\.(png|jpe?g|webp)$", entry.name, re.IGNORECASE)
                )
            except OSError:
                continue
            if images:
                return f"{relative_dir}/{images[0]}"
    return ""


def _add(entries: list, label: str, field: str, value, description: str,
         source_table: str, preview: str = "") -> None:
    """The Node addId guard: falsy values are simply absent, not reported."""
    if value is None or value == "" or value == 0 or value == "0":
        return
    entries.append(
        {
            "label": label,
            "field": field,
            "value": value,
            "description": description,
            "sourceTable": source_table,
            "preview": preview,
        }
    )


def _unit_stats(catalog: Catalog, record: dict) -> list[dict]:
    stat_data = (record.get("_stat") or {}).get("m_StatData") or {}
    base = stat_data.get("m_Stat") or {}
    per_level = stat_data.get("m_StatPerLevel") or {}
    return [
        {
            "statId": stat_type_value(stat_type),
            "statType": stat_type,
            "name": _stat_name(stat_type, catalog),
            "base": base.get(stat_type),
            "perLevel": per_level.get(stat_type),
            "fields": {
                "base": f"m_StatData.m_Stat.{stat_type}",
                "perLevel": f"m_StatData.m_StatPerLevel.{stat_type}",
            },
            "description": "The numeric stat ID is the client enum value; the two fields control the level-1 base and growth added per level.",
        }
        for stat_type in dict.fromkeys([*base.keys(), *per_level.keys()])
    ]


def _inspect_unit(roots: Roots, catalog: Catalog, object_type: str, record: dict) -> dict:
    source = record.get("_sourceTable") or "LUA_UNIT_TEMPLET_BASE.json"
    result = {**summarize(catalog, object_type, record), "ids": [], "stats": _unit_stats(catalog, record)}

    for label, field, description in [
        ("Unit ID", "m_UnitID", "Primary numeric identity used by inventory data, squads, rewards, contracts, skins, and network packets."),
        ("Unit string ID", "m_UnitStrID", "Canonical string key joining the base template to stats, battle templates, collection data, and other gameplay tables."),
        ("Base unit ID", "m_BaseUnitID", "Links variants, rearms, and alternate presentations back to their base character."),
        ("Ship group ID", "m_ShipGroupID", "Groups upgrade stages and related versions of the same ship line."),
        ("Operator passive group ID", "m_OprPassiveGroupID", "Selects the pool of passive skill IDs this operator can roll."),
        ("Tactical-update group ID", "m_TacticGroup", "Groups units that share tactical-update progression rules."),
        ("Team-up ID", "m_TeamUp", "Links this character to its collection/team affiliation."),
        ("Name localization ID", "m_Name", "Looks up the displayed unit name in the active language string table."),
        ("Title localization ID", "m_Title", "Looks up the displayed title or affiliation text."),
        ("Description localization ID", "m_UnitDesc", "Looks up the unit description shown by profile and collection UIs."),
        ("Battle template ID", "m_UnitTempletFileName", "Names the decoded battle-template file that defines states, attacks, animation events, and combat behavior."),
    ]:
        _add(result["ids"], label, field, record.get(field), description, source)
    for field, label, description in UNIT_ASSETS:
        value = record.get(field)
        _add(result["ids"], label, field, value, description, source, _asset_preview(roots, field, value))

    skill_table, id_field, icon_field = SKILL_TABLE[object_type]
    if object_type == "ship":
        skills = catalog.ship_skills
    elif object_type == "operator":
        skills = catalog.operator_skills_by_str
    else:
        skills = catalog.unit_skills
    for slot in range(1, 5):
        str_id = record.get(f"m_SkillStrID{slot}")
        if not str_id:
            continue
        _add(result["ids"], f"Skill {slot} string ID", f"m_SkillStrID{slot}", str_id,
             f"Selects skill slot {slot} and joins to its skill template.", source)
        for skill in _unique_by(skills.get(str(str_id), []), id_field):
            _add(result["ids"], f"Skill {slot} numeric ID", id_field, skill.get(id_field),
                 "Numeric skill identity used by skill levels, upgrades, combat state, and packets.", skill_table)
            icon = skill.get(icon_field)
            _add(result["ids"], f"Skill {slot} icon asset ID", icon_field, icon,
                 "Selects the icon displayed by skill panels and tooltips.", skill_table,
                 _asset_preview(roots, "m_UnitSkillIcon", icon))

    for skin in catalog.skins.get(str(record.get("m_UnitID")), []):
        _add(result["ids"], "Skin ID", "m_SkinID", skin.get("m_SkinID"),
             f"Selects the alternate {skin.get('m_SkinStrID') or 'skin'} presentation; equipped skin fields override the unit art IDs above.",
             "LUA_SKIN_TEMPLET.json")
        _add(result["ids"], "Skin string ID", "m_SkinStrID", skin.get("m_SkinStrID"),
             "Canonical string key for this alternate skin and its asset names.", "LUA_SKIN_TEMPLET.json")
    for collection in catalog.collections.get(str(record.get("m_UnitID")), []):
        _add(result["ids"], "Collection row ID", "Idx", collection.get("Idx"),
             "Places this unit in the collection/profile catalog.", "LUA_COLLECTION_UNIT_TEMPLET.json")
    if object_type == "operator":
        for passive in catalog.operator_passives.get(str(record.get("m_OprPassiveGroupID")), []):
            skill = (catalog.operator_skills_by_id.get(str(passive.get("m_OperSkillID"))) or [{}])[0]
            suffix = f" ({skill.get('m_OperSkillStrID')})" if skill.get("m_OperSkillStrID") else ""
            _add(result["ids"], "Passive skill numeric ID", "m_OperSkillID", passive.get("m_OperSkillID"),
                 f"A rollable passive in group {record.get('m_OprPassiveGroupID')}{suffix}.",
                 "LUA_OPERATOR_RANDOM_PASSIVE_TEMPLET.json")
    if object_type == "ship":
        for build in catalog.ship_builds.get(str(record.get("m_UnitID")), []):
            _add(result["ids"], "Ship build ID", "m_ShipID", build.get("m_ShipID"),
                 "Joins this ship to its construction and upgrade recipe.", "LUA_SHIP_BUILD_TEMPLET.json")
            _add(result["ids"], "Ship upgrade target ID", "m_ShipUpgradeTarget1", build.get("m_ShipUpgradeTarget1"),
                 "Unit ID produced by the next ship upgrade stage.", "LUA_SHIP_BUILD_TEMPLET.json")
            for slot in range(1, 5):
                _add(result["ids"], f"Build material {slot} item ID", f"m_ShipBuildMaterialID_{slot}",
                     build.get(f"m_ShipBuildMaterialID_{slot}"),
                     "Item/currency ID consumed by the ship construction recipe.", "LUA_SHIP_BUILD_TEMPLET.json")
    for field, label in [
        ("m_OnRemoveItemID_1", "Dismissal reward item ID 1"),
        ("m_OnRemoveItemID_2", "Dismissal reward item ID 2"),
        ("m_OnRemoveItemID_Contract", "Contract-dismissal reward item ID"),
        ("m_OnExtractItemID_1", "Extraction reward item ID"),
        ("m_OnExtractItemID_Contract", "Contract extraction item ID"),
    ]:
        _add(result["ids"], label, field, record.get(field),
             "References the item granted when this unit is dismissed or extracted under the matching rule.", source)
    return result


def _inspect_gear(roots: Roots, catalog: Catalog, record: dict) -> dict:
    source = "LUA_ITEM_EQUIP_TEMPLET.json"
    result = {**summarize(catalog, "gear", record), "ids": [], "stats": [], "gear_stat_ids": []}
    for label, field, description in [
        ("Gear ID", "m_ItemEquipID", "Primary numeric identity used by inventory instances, rewards, crafting, upgrades, and packets."),
        ("Gear string ID", "m_ItemEquipStrID", "Canonical string key for this gear template."),
        ("Name localization ID", "m_ItemEquipName", "Looks up the displayed gear name."),
        ("Description localization ID", "m_ItemEquipDesc", "Looks up the displayed gear description."),
    ]:
        _add(result["ids"], label, field, record.get(field), description, source)
    icon = record.get("m_ItemEquipIconName")
    _add(result["ids"], "Inventory icon PNG ID", "m_ItemEquipIconName", icon,
         "Selects the gear PNG shown in inventory, equipment, reward, and crafting slots.", source,
         _asset_preview(roots, "m_ItemEquipIconName", icon))
    for label, field, description in [
        ("Random stat group ID 1", "m_StatGroupID", "Selects every allowed first tuning substat and its minimum/maximum roll."),
        ("Random stat group ID 2", "m_StatGroupID_2", "Selects every allowed second tuning substat and its minimum/maximum roll."),
        ("Primary potential group ID", "m_PotentialOptionGroupID", "Selects relic potential options and per-socket ranges."),
        ("Secondary potential group ID", "m_SubPotentialOptionGroupID", "Selects the secondary relic potential option pool."),
    ]:
        _add(result["ids"], label, field, record.get(field), description, source)
    for set_id in _array_value(record.get("m_SetGroup")):
        option = catalog.set_options.get(str(set_id), {})
        name = option.get("m_EquipSetStrID") or option.get("m_EquipSetName") or "referenced"
        _add(result["ids"], "Allowed set-option ID", "m_SetGroup[]", set_id,
             f"Allows this gear to roll the {name} set bonus.", "LUA_ITEM_EQUIP_SET_OPTION.json")
    for field, label in [
        ("m_OnRemoveItemID_1", "Dismantle reward item ID 1"),
        ("m_OnRemoveItemID_2", "Dismantle reward item ID 2"),
        ("m_RandomSetReqItemID", "Set reroll material item ID"),
        ("m_RelicRerollReqItemID", "Relic reroll material item ID"),
        ("Socket1_OpenItemID", "Socket 1 unlock item ID"),
        ("Socket2_OpenItemID", "Socket 2 unlock item ID"),
        ("Socket3_OpenItemID", "Socket 3 unlock item ID"),
    ]:
        _add(result["ids"], label, field, record.get(field),
             "References the item consumed or granted by the matching gear operation.", source)

    _add_main_gear_stat(catalog, result["stats"], record)
    _add_random_gear_stats(catalog, result["stats"], record)
    _add_potential_gear_stats(catalog, result["stats"], record)
    return result


def _add_main_gear_stat(catalog: Catalog, out: list, gear: dict) -> None:
    stat_type = str(gear.get("STAT_TYPE_1") or "")
    if not stat_type:
        return
    minimum = _number_or_none(gear.get("STAT_VALUE_1"))
    per_level = _number_or_none(gear.get("STAT_LEVELUP_VALUE_1")) or 0
    max_level = _number_or_none(gear.get("m_MaxEnchantLevel")) or 0
    out.append({
        "statId": stat_type_value(stat_type), "statType": stat_type, "name": _stat_name(stat_type, catalog),
        "slot": "Main", "groupId": None, "optionKey": None, "precisionWeightId": None,
        "min": minimum, "max": None if minimum is None else minimum + per_level * max_level,
        "fields": {"type": "STAT_TYPE_1", "min": "STAT_VALUE_1", "perLevel": "STAT_LEVELUP_VALUE_1", "maxLevel": "m_MaxEnchantLevel"},
        "sourceTable": "LUA_ITEM_EQUIP_TEMPLET.json",
        "description": f"Main stat range from enhancement +0 through +{max_level}; max = base + per-level value times max enchant level.",
    })


def _add_random_gear_stats(catalog: Catalog, out: list, gear: dict) -> None:
    for field, slot in (("m_StatGroupID", "Substat 1"), ("m_StatGroupID_2", "Substat 2")):
        group_id = _number_or_none(gear.get(field))
        if not group_id:
            continue
        for row in catalog.random_stats.get(str(group_id), []):
            stat_type = _normalize_rate_stat(row.get("m_StatType"), row)
            min_field = _first_field(row, ["m_MinStatValue", "m_MinStatRate", "m_MinStat"])
            max_field = _first_field(row, ["m_MaxStatValue", "m_MaxStatRate", "m_MaxStat"])
            out.append({
                "statId": stat_type_value(stat_type), "statType": stat_type, "name": _stat_name(stat_type, catalog),
                "slot": slot, "groupId": group_id, "optionKey": None, "precisionWeightId": None,
                "min": _number_or_none(row.get(min_field)) if min_field else None,
                "max": _number_or_none(row.get(max_field)) if max_field else None,
                "fields": {"group": field, "type": "m_StatType", "min": min_field, "max": max_field},
                "sourceTable": "LUA_ITEM_EQUIP_RANDOM_STAT.json",
                "description": f"{field} selects group {group_id}; this row defines one stat ID that slot may roll and its raw tuning range.",
            })


def _add_potential_gear_stats(catalog: Catalog, out: list, gear: dict) -> None:
    for field, label in (("m_PotentialOptionGroupID", "Primary potential"),
                         ("m_SubPotentialOptionGroupID", "Secondary potential")):
        group_id = _number_or_none(gear.get(field))
        if not group_id:
            continue
        for row in catalog.potentials.get(str(group_id), []):
            for socket in range(1, 4):
                min_field = _first_field(row, [f"Socket{socket}_MinStat", f"Socket{socket}_MinStatRate"])
                max_field = _first_field(row, [f"Socket{socket}_MaxStat", f"Socket{socket}_MaxStatRate"])
                if not min_field and not max_field:
                    continue
                stat_type = _normalize_rate_stat(row.get("Socket1_StatType"), row)
                out.append({
                    "statId": stat_type_value(stat_type), "statType": stat_type,
                    "name": _stat_name(stat_type, catalog), "slot": f"{label} | Socket {socket}", "groupId": group_id,
                    "optionKey": _number_or_none(row.get("OptionKey")),
                    "precisionWeightId": _number_or_none(row.get("PrecisionWeightId")),
                    "min": _number_or_none(row.get(min_field)) if min_field else None,
                    "max": _number_or_none(row.get(max_field)) if max_field else None,
                    "fields": {"group": field, "option": "OptionKey", "precisionWeight": "PrecisionWeightId",
                               "type": "Socket1_StatType", "min": min_field, "max": max_field},
                    "sourceTable": "LUA_ITEM_EQUIP_POTENTIAL_OPTION.json",
                    "description": f"{field} selects group {group_id}; OptionKey identifies the potential and PrecisionWeightId controls precision-roll weighting.",
                })


# --------------------------------------------------------------------------
# Public tools
# --------------------------------------------------------------------------


def list_objects(roots: Roots, object_type=None, query: str = "", offset: int = 0, limit: int = 100) -> dict:
    object_type = normalize_object_type(object_type)
    catalog = Catalog(roots)
    needle = str(query or "").strip().lower()
    rows = [summarize(catalog, object_type, record) for record in catalog.records(object_type)]
    if needle:
        rows = [
            row
            for row in rows
            if needle
            in " ".join([str(row["id"]), row["name"], row["strId"], row["meta"]]).lower()
        ]
    offset = max(0, int(_number_or_none(offset) or 0))
    limit = max(1, min(250, int(_number_or_none(limit) or 100)))
    return {
        "type": object_type,
        "total": len(rows),
        "offset": offset,
        "limit": limit,
        "objects": rows[offset : offset + limit],
    }


def _find_record(catalog: Catalog, object_type: str, object_id) -> dict | None:
    target = int(_number_or_none(object_id) or 0)
    for record in catalog.records(object_type):
        if _object_id(object_type, record) == target:
            return record
    return None


def get_object(roots: Roots, object_type: str, object_id) -> dict:
    object_type = normalize_object_type(object_type)
    catalog = Catalog(roots)
    record = _find_record(catalog, object_type, object_id)
    if record is None:
        raise DomainError(f"{object_type} was not found: {object_id}", status=404)
    if object_type == "gear":
        return _inspect_gear(roots, catalog, record)
    return _inspect_unit(roots, catalog, object_type, record)


def find_asset_for_object(roots: Roots, object_type: str, object_id, field_name: str | None = None) -> dict:
    """Every asset-bearing field on one object, resolved to a relative path."""
    object_type = normalize_object_type(object_type)
    catalog = Catalog(roots)
    record = _find_record(catalog, object_type, object_id)
    if record is None:
        raise DomainError(f"{object_type} was not found: {object_id}", status=404)
    fields = [field_name] if field_name else ASSET_FIELDS
    assets = []
    for field in fields:
        value = record.get(field)
        if not value:
            continue
        assets.append({"field": field, "value": value, "path": _asset_preview(roots, field, str(value))})
    return {"type": object_type, "id": _object_id(object_type, record), "assets": assets}
