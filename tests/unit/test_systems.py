import json
from pathlib import Path

import pytest

from counterside_mcp.config import Roots
from counterside_mcp.systems import list_systems, load_systems, search_fields


def build_roots(tmp_path: Path) -> Roots:
    luac = tmp_path / "StreamingAssets" / "ab_script_unit_data" / "luac"
    luac.mkdir(parents=True)
    (luac / "LUA_UNIT_TEMPLET_BASE.json").write_text(
        json.dumps(
            {
                "records": [
                    {"m_UnitID": 1, "m_RespawnCost": 5, "m_StatData": {"m_Stat": {"NST_HP": 100}}}
                ]
            }
        )
    )
    return Roots(
        tmp_path,
        (tmp_path / "assets",),
        (tmp_path / "StreamingAssets",),
        tmp_path / "wiki",
        tmp_path / "server-data",
    )


def test_systems_loaded_verbatim():
    systems = load_systems()
    assert len(systems) == 29
    assert {s.id for s in systems} >= {"units", "items", "stages", "story", "all"}


def test_every_system_has_display_fields():
    for system in load_systems():
        assert system.id and system.title and system.description


def test_list_systems_reports_table_counts(tmp_path):
    roots = build_roots(tmp_path)
    report = list_systems(roots)
    assert report["tableCount"] >= 1
    units = next(s for s in report["systems"] if s["id"] == "units")
    assert units["tableCount"] >= 1
    assert units["title"]


def test_search_fields_finds_deploy_cost(tmp_path):
    roots = build_roots(tmp_path)
    result = search_fields(roots, "unit respawn cost")
    assert result["systems"]
    assert any("UNIT" in table["tableName"] for table in result["tables"])
    assert any("Respawn" in field["path"] for field in result["fields"])


def test_search_fields_ranks_the_matching_field_above_unrelated_ones(tmp_path):
    """A field whose own name matches must outrank fields that merely share a table."""
    roots = build_roots(tmp_path)
    fields = search_fields(roots, "unit respawn cost")["fields"]
    paths = [field["path"] for field in fields]
    assert "m_RespawnCost" in paths
    # The matching field must not be buried behind unrelated fields in a big table.
    assert paths.index("m_RespawnCost") < 5


def test_search_fields_ranks_matching_table_names_by_relevance(tmp_path):
    roots = build_roots(tmp_path)
    tables = search_fields(roots, "unit respawn cost")["tables"]
    assert tables[0]["tableName"] == "LUA_UNIT_TEMPLET_BASE"


def test_search_fields_rejects_short_query(tmp_path):
    roots = build_roots(tmp_path)
    with pytest.raises(ValueError):
        search_fields(roots, "a")


def test_search_fields_on_unknown_concept_returns_empty_not_error(tmp_path):
    roots = build_roots(tmp_path)
    result = search_fields(roots, "zzzznotathing")
    assert result["tables"] == []
    assert result["fields"] == []
