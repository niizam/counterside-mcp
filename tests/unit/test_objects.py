import json
from pathlib import Path

import pytest

from counterside_mcp.config import Roots
from counterside_mcp.errors import DomainError
from counterside_mcp.objects import (
    find_asset_for_object,
    get_object,
    list_objects,
    normalize_object_type,
)


def write(tmp_path, directory, name, records):
    luac = tmp_path / "StreamingAssets" / directory / "luac"
    luac.mkdir(parents=True, exist_ok=True)
    (luac / f"{name}.json").write_text(json.dumps({"records": records}))


def build_roots(tmp_path: Path) -> Roots:
    write(tmp_path, "ab_script_unit_data", "LUA_UNIT_TEMPLET_BASE", [
        {
            "m_UnitID": 204, "m_UnitStrID": "NKM_SHIP_A_COFFIN_TR_1", "m_BaseUnitID": 100,
            "m_ShipGroupID": 1, "m_NKM_UNIT_TYPE": "NUT_SHIP", "m_NKM_UNIT_GRADE": "NUG_R",
            "m_Name": "SI_BLANK", "m_Title": "SI_BLANK",
            "m_InvenIconName": "AB_INVEN_ICON_NKM_SHIP_A_COFFIN",
            "m_FaceCardName": "AB_UNIT_FACE_CARD_NKM_SHIP_A_COFFIN",
            "m_SkillStrID1": "SS_NKM_SHIP_COFFIN_PASSIVE1",
            "m_OnRemoveItemID_1": 1, "m_OnRemoveItemCount_1": 3500,
        },
        {
            "m_UnitID": 1001, "m_UnitStrID": "NKM_UNIT_A", "m_NKM_UNIT_TYPE": "NUT_COUNTER",
            "m_NKM_UNIT_GRADE": "NUG_SSR", "m_Name": "SI_UNIT_A",
            "m_SkillStrID1": "US_A_1",
        },
    ])
    write(tmp_path, "ab_script_unit_data", "LUA_UNIT_STAT_TEMPLET", [
        {
            "m_UnitStrID": "NKM_UNIT_A", "m_RespawnCost": 4, "m_RespawnCount": 2,
            "m_StatData": {"m_Stat": {"NST_HP": 1603}, "m_StatPerLevel": {"NST_HP": 206}},
        },
    ])
    write(tmp_path, "ab_script_unit_data", "LUA_UNIT_SKILL_TEMPLET", [
        {"m_UnitSkillStrID": "US_A_1", "m_UnitSkillID": 9001, "m_UnitSkillIcon": "ICON_A_1", "m_Level": 1},
    ])
    write(tmp_path, "ab_script", "LUA_SHIP_SKILL_TEMPLET", [
        {"m_ShipSkillStrID": "SS_NKM_SHIP_COFFIN_PASSIVE1", "m_ShipSkillID": 7500, "m_ShipSkillIcon": "ICON_SHIP_1"},
    ])
    write(tmp_path, "ab_script", "LUA_SKIN_TEMPLET", [
        {"m_SkinID": 5001, "m_SkinStrID": "SKIN_A", "m_SkinEquipUnitID": 1001},
    ])
    write(tmp_path, "ab_script_item_templet", "LUA_ITEM_EQUIP_TEMPLET", [
        {
            "m_ItemEquipID": 90001, "m_ItemEquipStrID": "IQI_EQUIP_ENCHANT_MODULE_T1",
            "m_ItemEquipName": "SI_ITEM_NAME_IQI", "m_NKM_ITEM_TIER": 1, "m_NKM_ITEM_GRADE": "NIG_SR",
            "m_ItemEquipPosition": "IEP_ACC", "m_ItemEquipIconName": "IQI_EQUIP_COUNTER_ACC_TEST",
            "m_MaxEnchantLevel": 10,
            "STAT_TYPE_1": "NST_HP", "STAT_VALUE_1": 100, "STAT_LEVELUP_VALUE_1": 10,
            "m_StatGroupID": 101001, "m_PotentialOptionGroupID": 99990403, "m_SetGroup": [220800],
            "m_RandomSetReqItemID": 55,
        },
    ])
    write(tmp_path, "ab_script", "LUA_ITEM_EQUIP_RANDOM_STAT", [
        {"m_StatGroupID": 101001, "m_StatType": "NST_CRITICAL_DAMAGE_RATE",
         "m_MinStat": 0.067, "m_MaxStat": 0.2, "m_MinStatValue": 0.067, "m_MaxStatValue": 0.2},
    ])
    write(tmp_path, "ab_script", "LUA_ITEM_EQUIP_POTENTIAL_OPTION", [
        {"m_PotentialOptionGroupID": 99990403, "OptionKey": 1, "Socket1_StatType": "NST_HP",
         "PrecisionWeightId": 100, "Socket1_MinStat": 300, "Socket1_MaxStat": 500},
    ])
    write(tmp_path, "ab_script_item_templet", "LUA_ITEM_EQUIP_SET_OPTION", [
        {"m_EquipSetID": 220800, "m_EquipSetStrID": "SET_NORMAL_2P_ATK_RATE", "m_StatType_1": "NST_ATK"},
    ])
    icons = tmp_path / "assets" / "Data" / "StreamingAssets" / "ab_inven_icon_unit" / "Texture2D"
    icons.mkdir(parents=True)
    (icons / "AB_INVEN_ICON_NKM_SHIP_A_COFFIN.png").write_bytes(b"\x89PNG")
    # The shipped naming: gear icons are AB_INVEN_ICON_IQI_EQUIP_<value>.png.
    gear_icons = tmp_path / "assets" / "Data" / "StreamingAssets" / "ab_inven_icon_item_equip" / "Texture2D"
    gear_icons.mkdir(parents=True)
    (gear_icons / "AB_INVEN_ICON_IQI_EQUIP_IQI_EQUIP_COUNTER_ACC_TEST.png").write_bytes(b"\x89PNG")
    return Roots(
        tmp_path,
        (tmp_path / "assets",),
        (tmp_path / "StreamingAssets",),
        tmp_path / "wiki",
        tmp_path / "server-data",
    )


def test_normalize_object_type_defaults_and_rejects():
    assert normalize_object_type(None) == "unit"
    assert normalize_object_type("Gear") == "gear"
    with pytest.raises(DomainError):
        normalize_object_type("weapon")


def test_list_splits_types(tmp_path):
    roots = build_roots(tmp_path)
    assert list_objects(roots, "ship", "", 0, 100)["total"] == 1
    assert list_objects(roots, "unit", "", 0, 100)["total"] == 1
    assert list_objects(roots, "gear", "", 0, 100)["total"] == 1


def test_list_objects_summarizes(tmp_path):
    roots = build_roots(tmp_path)
    row = list_objects(roots, "ship", "", 0, 100)["objects"][0]
    assert row["id"] == 204
    assert row["strId"] == "NKM_SHIP_A_COFFIN_TR_1"
    assert row["meta"]


def test_list_objects_query_filters(tmp_path):
    roots = build_roots(tmp_path)
    assert list_objects(roots, "unit", "COFFIN", 0, 100)["total"] == 0
    assert list_objects(roots, "ship", "COFFIN", 0, 100)["total"] == 1
    assert list_objects(roots, "ship", "zzz", 0, 100)["total"] == 0


def test_listing_units_skips_inspection_only_tables(tmp_path):
    """Listing must not pay for the skill, skin and set-option tables."""
    from counterside_mcp.objects import Catalog

    roots = build_roots(tmp_path)
    catalog = Catalog(roots)
    assert catalog.records("unit")
    assert "ship_skills" not in catalog._loaded
    assert "potentials" not in catalog._loaded


def test_unit_table_is_reused_across_calls(tmp_path):
    from counterside_mcp.objects import _load_units

    roots = build_roots(tmp_path)
    _load_units.cache_clear()
    list_objects(roots, "unit", "", 0, 10)
    list_objects(roots, "unit", "", 0, 10)
    assert _load_units.cache_info().hits >= 1


def test_list_objects_pagination(tmp_path):
    roots = build_roots(tmp_path)
    page = list_objects(roots, "ship", "", 0, 100)
    assert page["offset"] == 0
    assert page["limit"] <= 250
    assert len(page["objects"]) <= page["limit"]


def test_get_ship_maps_ids_and_assets(tmp_path):
    roots = build_roots(tmp_path)
    obj = get_object(roots, "ship", 204)
    fields = {entry["field"]: entry for entry in obj["ids"]}
    assert fields["m_UnitID"]["value"] == 204
    assert fields["m_BaseUnitID"]["value"] == 100
    assert fields["m_InvenIconName"]["preview"].endswith("AB_INVEN_ICON_NKM_SHIP_A_COFFIN.png")
    assert fields["m_FaceCardName"]["preview"] == ""
    assert any(s["field"] == "m_ShipSkillID" and s["value"] == 7500 for s in obj["ids"])


def test_get_object_uses_ship_skills_for_ships(tmp_path):
    roots = build_roots(tmp_path)
    obj = get_object(roots, "ship", 204)
    assert not any(s["field"] == "m_UnitSkillID" for s in obj["ids"])


def test_get_unit_uses_unit_skills_and_stats(tmp_path):
    roots = build_roots(tmp_path)
    obj = get_object(roots, "unit", 1001)
    assert any(s["field"] == "m_UnitSkillID" and s["value"] == 9001 for s in obj["ids"])
    stat = obj["stats"][0]
    assert stat["statType"] == "NST_HP"
    assert stat["base"] == 1603
    assert stat["perLevel"] == 206
    assert any(entry["field"] == "m_SkinID" and entry["value"] == 5001 for entry in obj["ids"])


def test_get_gear_reports_stat_ranges(tmp_path):
    roots = build_roots(tmp_path)
    gear = get_object(roots, "gear", 90001)
    assert gear["id"] == 90001
    main = next(s for s in gear["stats"] if s["slot"] == "Main")
    assert main["statType"] == "NST_HP"
    assert main["min"] == 100
    assert main["max"] == 200  # 100 base + 10 per level * 10 max enchant levels
    substat = next(s for s in gear["stats"] if s["slot"] == "Substat 1")
    assert substat["statType"] == "NST_CRITICAL_DAMAGE_RATE"
    assert substat["min"] == 0.067
    potential = next(s for s in gear["stats"] if s["slot"].endswith("Socket 1"))
    assert potential["min"] == 300 and potential["max"] == 500


def test_get_gear_links_set_and_reroll_items(tmp_path):
    roots = build_roots(tmp_path)
    gear = get_object(roots, "gear", 90001)
    assert any(e["field"] == "m_SetGroup[]" and e["value"] == 220800 for e in gear["ids"])
    assert any(e["field"] == "m_RandomSetReqItemID" and e["value"] == 55 for e in gear["ids"])


def test_get_object_missing_raises(tmp_path):
    roots = build_roots(tmp_path)
    with pytest.raises(DomainError):
        get_object(roots, "ship", 999999)


def test_find_asset_for_object_returns_all_asset_fields(tmp_path):
    roots = build_roots(tmp_path)
    result = find_asset_for_object(roots, "ship", 204)
    by_field = {a["field"]: a for a in result["assets"]}
    assert by_field["m_InvenIconName"]["path"].endswith(".png")
    assert by_field["m_FaceCardName"]["path"] == ""


def test_find_asset_for_object_single_field(tmp_path):
    roots = build_roots(tmp_path)
    result = find_asset_for_object(roots, "ship", 204, "m_InvenIconName")
    assert [a["field"] for a in result["assets"]] == ["m_InvenIconName"]


def test_gear_icon_resolves_with_shipped_prefix(tmp_path):
    """Gear icons on disk are AB_INVEN_ICON_IQI_EQUIP_<value>.png, not the ..._ICON_<value>.png
    the upstream catalog looks for — which resolves nothing for any gear item."""
    roots = build_roots(tmp_path)
    result = find_asset_for_object(roots, "gear", 90001, "m_ItemEquipIconName")
    assert result["assets"][0]["path"].endswith("AB_INVEN_ICON_IQI_EQUIP_IQI_EQUIP_COUNTER_ACC_TEST.png")
