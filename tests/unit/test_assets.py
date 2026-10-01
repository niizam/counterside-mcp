import json
from pathlib import Path

import pytest

from counterside_mcp.assets import (
    asset_bytes,
    asset_metadata,
    find_related,
    list_directory,
    spine_set,
    text_preview,
)
from counterside_mcp.config import Roots
from counterside_mcp.errors import DomainError


def build_roots(tmp_path: Path) -> Roots:
    assets = tmp_path / "assets"
    spine = assets / "Data" / "StreamingAssets" / "ab_unit_sd_spine_demo" / "TextAsset"
    spine.mkdir(parents=True)
    (spine / "DEMO.atlas").write_text("DEMO.png\nsize: 64,64\n")
    (spine / "DEMO.skel").write_bytes(b"skel")
    (spine.parent / "Texture2D").mkdir()
    (spine.parent / "Texture2D" / "DEMO.png").write_bytes(b"\x89PNG")
    docs = assets / "Data" / "StreamingAssets"
    (docs / "a.json").write_text('{"hello":"world"}')
    (docs / "notes.txt").write_text("plain text")
    return Roots(
        tmp_path,
        (assets,),
        (tmp_path / "tables",),
        tmp_path / "wiki" / "data",  # config.resolve_roots points at the data dir
        tmp_path / "server-data",
    )


def test_list_directory_returns_typed_entries(tmp_path):
    roots = build_roots(tmp_path)
    result = list_directory(roots, "Data/StreamingAssets", "", 0, 100)
    by_name = {entry["name"]: entry for entry in result["entries"]}
    assert by_name["ab_unit_sd_spine_demo"]["kind"] == "directory"
    assert by_name["a.json"]["assetType"] == "JSON"
    assert by_name["a.json"]["size"] > 0
    assert result["parentPath"] == "Data"


def test_list_directory_sorts_directories_first(tmp_path):
    roots = build_roots(tmp_path)
    entries = list_directory(roots, "Data/StreamingAssets", "", 0, 100)["entries"]
    kinds = [entry["kind"] for entry in entries]
    assert kinds == sorted(kinds, key=lambda kind: kind != "directory")


def test_list_directory_filters_by_query(tmp_path):
    roots = build_roots(tmp_path)
    result = list_directory(roots, "Data/StreamingAssets", "notes", 0, 100)
    assert [entry["name"] for entry in result["entries"]] == ["notes.txt"]


def test_list_directory_rejects_traversal(tmp_path):
    roots = build_roots(tmp_path)
    with pytest.raises(DomainError):
        list_directory(roots, "../../etc", "", 0, 10)


def test_asset_metadata_describes_a_file(tmp_path):
    roots = build_roots(tmp_path)
    meta = asset_metadata(roots, "Data/StreamingAssets/a.json")
    assert meta["name"] == "a.json"
    assert meta["extension"] == ".json"
    assert meta["isImage"] is False
    assert "json" in meta["contentType"]


def test_asset_metadata_rejects_a_directory(tmp_path):
    roots = build_roots(tmp_path)
    with pytest.raises(DomainError):
        asset_metadata(roots, "Data/StreamingAssets")


def test_asset_bytes_returns_content_and_type(tmp_path):
    roots = build_roots(tmp_path)
    data, content_type = asset_bytes(roots, "Data/StreamingAssets/a.json")
    assert data.startswith(b"{")
    assert "json" in content_type


def test_text_preview_reads_and_flags_truncation(tmp_path):
    roots = build_roots(tmp_path)
    full = text_preview(roots, "Data/StreamingAssets/notes.txt", 1024)
    assert full["text"] == "plain text"
    assert full["truncated"] is False
    clipped = text_preview(roots, "Data/StreamingAssets/notes.txt", 4)
    assert clipped["text"] == "plai"
    assert clipped["truncated"] is True


def test_text_preview_rejects_binary(tmp_path):
    roots = build_roots(tmp_path)
    with pytest.raises(DomainError):
        text_preview(roots, "Data/StreamingAssets/ab_unit_sd_spine_demo/Texture2D/DEMO.png", 1024)


def test_spine_set_resolves_every_role(tmp_path):
    roots = build_roots(tmp_path)
    result = spine_set(roots, "Data/StreamingAssets/ab_unit_sd_spine_demo/TextAsset/DEMO.skel")
    assert result["ready"] is True
    roles = {item["role"] for item in result["files"]}
    assert roles == {"skeleton", "atlas", "texture"}
    texture = next(item for item in result["files"] if item["role"] == "texture")
    assert texture["name"] == "DEMO.png"


def test_spine_set_reports_missing_texture(tmp_path):
    roots = build_roots(tmp_path)
    (tmp_path / "assets/Data/StreamingAssets/ab_unit_sd_spine_demo/Texture2D/DEMO.png").unlink()
    result = spine_set(roots, "Data/StreamingAssets/ab_unit_sd_spine_demo/TextAsset/DEMO.atlas")
    assert result["ready"] is False
    assert any("DEMO.png" in item for item in result["missing"])


def test_spine_set_rejects_a_non_spine_extension(tmp_path):
    roots = build_roots(tmp_path)
    with pytest.raises(DomainError):
        spine_set(roots, "Data/StreamingAssets/notes.txt")


def test_find_related_matches_the_same_asset_name(tmp_path):
    roots = build_roots(tmp_path)
    result = find_related(roots, "Data/StreamingAssets/ab_unit_sd_spine_demo/TextAsset/DEMO.atlas")
    paths = {asset["path"] for asset in result["assets"]}
    # The skeleton shares the DEMO stem, so it is a related asset.
    assert any(path.endswith("DEMO.skel") for path in paths)


def test_find_related_reports_tables_for_a_json_reference(tmp_path):
    roots = build_roots(tmp_path)
    # A table index that references the string inside the JSON file.
    # wiki_dir is the data directory itself, as config.resolve_roots sets it.
    wiki = tmp_path / "wiki" / "data"
    wiki.mkdir(parents=True)
    (wiki / "idIndex.json").write_text(json.dumps([
        {"id": 1, "idField": "m_ID", "table": "T.json", "name": "world",
         "strId": "world", "type": "", "source": "ab/luac/T.json", "image": ""},
    ]))
    result = find_related(roots, "Data/StreamingAssets/a.json")
    assert [row["table"] for row in result["tables"]] == ["T.json"]
    assert "matchedBy" in result["tables"][0]


def test_find_related_missing_file_raises(tmp_path):
    roots = build_roots(tmp_path)
    with pytest.raises(DomainError):
        find_related(roots, "Data/StreamingAssets/nope.txt")


def test_bundle_root_prefers_the_bundle_over_its_container(tmp_path):
    """An extracted tree marks each bundle with manifest.json. Without that
    check the upstream depth-2 fallback returns Data/StreamingAssets itself,
    turning every related-name lookup into a walk of the whole tree."""
    from counterside_mcp.assets import _bundle_root

    roots = build_roots(tmp_path)
    bundle = tmp_path / "assets" / "Data" / "StreamingAssets" / "ab_icon_bundle"
    (bundle / "Texture2D").mkdir(parents=True)
    (bundle / "manifest.json").write_text("{}")
    icon = bundle / "Texture2D" / "AB_ICON.png"
    icon.write_bytes(b"\x89PNG")
    assert _bundle_root(roots, icon) == bundle


def test_relation_collection_takes_any_four_letter_word(tmp_path):
    """Upstream's name-regex carries the /i flag, so `world` is a candidate term
    under a plain key. Ports that omit the flag silently find nothing."""
    from counterside_mcp.assets import _collect_relation_values

    terms, ids, path_ids = set(), set(), set()
    _collect_relation_values({"hello": "world"}, "", terms, ids, path_ids)
    assert terms == {"world"}


def test_relation_collection_ignores_non_integer_numbers(tmp_path):
    """Values are collected only when they are safe integers, so a float is
    skipped whole rather than truncated to its integer part."""
    from counterside_mcp.assets import _collect_relation_values

    terms, ids, path_ids = set(), set(), set()
    _collect_relation_values({"m_UnitID": 12.5, "m_OtherID": 42}, "", terms, ids, path_ids)
    assert ids == {"42"}
