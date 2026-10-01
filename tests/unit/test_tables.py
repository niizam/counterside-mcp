import json
from pathlib import Path

from counterside_mcp.config import Roots
from counterside_mcp.tables import (
    extract_table_records,
    find_table_entry,
    list_table_entries,
    normalize_table_base_name,
    parse_table_path,
    read_table_records,
    table_schema,
)


def build_roots(tmp_path: Path) -> Roots:
    table_root = tmp_path / "StreamingAssets"
    luac = table_root / "ab_script" / "luac"
    luac.mkdir(parents=True)
    (luac / "LUA_DEMO_TEMPLET.json").write_text(
        json.dumps(
            {
                "recordCount": 2,
                "records": [{"m_ID": 1, "m_Stat": {"hp": 10}}, {"m_ID": 2, "m_Stat": {"hp": 20}}],
            }
        )
    )
    return Roots(
        revival_root=tmp_path,
        asset_dirs=(tmp_path / "assets",),
        table_dirs=(table_root,),
        wiki_dir=tmp_path / "wiki",
        server_data_dir=tmp_path / "server-data",
    )


def test_normalize_table_base_name_strips_suffixes():
    assert normalize_table_base_name("LUA_X.json") == "LUA_X"
    assert normalize_table_base_name("LUA_X.luac.json") == "LUA_X"
    assert normalize_table_base_name("LUA_X.luac") == "LUA_X"
    assert normalize_table_base_name("path/to/LUA_X.json") == "LUA_X"


def test_parse_table_path_requires_luac_segment(tmp_path):
    assert parse_table_path(tmp_path, tmp_path / "x.json") is None
    entry = parse_table_path(tmp_path, tmp_path / "ab" / "luac" / "LUA_X.json")
    assert entry.directory == "ab" and entry.table_name == "LUA_X"


def test_parse_table_path_rejects_luac_first_or_last(tmp_path):
    """A 'luac' segment that is first or last is not a table path."""
    assert parse_table_path(tmp_path, tmp_path / "luac" / "LUA_X.json") is None
    assert parse_table_path(tmp_path, tmp_path / "ab" / "luac") is None


def test_extract_table_records_shapes():
    assert extract_table_records([{"a": 1}]) == [{"a": 1}]
    assert extract_table_records({"records": [{"a": 1}]}) == [{"a": 1}]
    assert extract_table_records({"root": [{"a": 1}]}) == [{"a": 1}]
    keyed = extract_table_records({"root": {"K": {"a": 1}}})
    assert keyed == [{"__key": "K", "a": 1}]
    assert extract_table_records(None) == []
    assert extract_table_records("nope") == []


def test_list_and_read(tmp_path):
    roots = build_roots(tmp_path)
    entries = list_table_entries(roots)
    assert [e.table_name for e in entries] == ["LUA_DEMO_TEMPLET"]
    found = find_table_entry(roots, "ab_script", "LUA_DEMO_TEMPLET")
    assert found is not None
    records, _ = read_table_records(roots, "ab_script", "LUA_DEMO_TEMPLET")
    assert [r["m_ID"] for r in records] == [1, 2]


def test_json_preferred_over_luac_when_both_exist(tmp_path):
    roots = build_roots(tmp_path)
    luac = tmp_path / "StreamingAssets" / "ab_script" / "luac"
    (luac / "LUA_DEMO_TEMPLET.luac").write_text(json.dumps({"records": [{"m_ID": 99}]}))
    entries = list_table_entries(roots)
    assert len(entries) == 1
    assert entries[0].extension == ".json"
    records, _ = read_table_records(roots, "ab_script", "LUA_DEMO_TEMPLET")
    assert [r["m_ID"] for r in records] == [1, 2]


def test_find_table_entry_accepts_name_with_extension(tmp_path):
    roots = build_roots(tmp_path)
    assert find_table_entry(roots, "ab_script", "LUA_DEMO_TEMPLET.json") is not None
    assert find_table_entry(roots, "ab_script", "LUA_MISSING") is None
    assert find_table_entry(roots, "wrong_dir", "LUA_DEMO_TEMPLET") is None


def test_table_schema_collects_nested_paths(tmp_path):
    roots = build_roots(tmp_path)
    records, _ = read_table_records(roots, "ab_script", "LUA_DEMO_TEMPLET")
    paths = {field["path"] for field in table_schema(records)}
    assert {"m_ID", "m_Stat.hp"} <= paths


def test_read_table_records_reports_not_found(tmp_path):
    roots = build_roots(tmp_path)
    records, meta = read_table_records(roots, "ab_script", "LUA_NOPE")
    assert records == []
    assert meta["found"] is False


def test_undecodable_table_yields_no_records(tmp_path):
    roots = build_roots(tmp_path)
    luac = tmp_path / "StreamingAssets" / "ab_script" / "luac"
    (luac / "LUA_BROKEN.json").write_text("{not valid json")
    records, meta = read_table_records(roots, "ab_script", "LUA_BROKEN")
    assert records == []
