from pathlib import Path

import pytest

from counterside_mcp.config import expand_root, health, resolve_roots
from counterside_mcp.errors import DomainError


def make_tree(tmp_path: Path) -> Path:
    (tmp_path / "extracted-assets" / "all" / "Data").mkdir(parents=True)
    (tmp_path / "gameplay-jsons" / "StreamingAssets" / "ab_script" / "luac").mkdir(parents=True)
    (tmp_path / "wiki" / "data").mkdir(parents=True)
    (tmp_path / "server-data").mkdir(parents=True)
    return tmp_path


def test_revival_root_from_env(tmp_path):
    root = make_tree(tmp_path)
    roots = resolve_roots(env={"CS_REVIVALSIDE_ROOT": str(root)})
    assert roots.revival_root == root
    assert roots.asset_dirs[0] == root / "extracted-assets" / "all"


def test_explicit_asset_root_override(tmp_path):
    root = make_tree(tmp_path)
    custom = tmp_path / "custom-assets"
    custom.mkdir()
    roots = resolve_roots(env={"CS_REVIVALSIDE_ROOT": str(root)}, explicit_asset_root=str(custom))
    assert roots.asset_dirs[0] == custom


def test_table_roots_from_env_are_expanded_to_both_layouts(tmp_path):
    root = make_tree(tmp_path)
    tables = tmp_path / "tables"
    tables.mkdir()
    roots = resolve_roots(env={"CS_REVIVALSIDE_ROOT": str(root), "CS_GAMEPLAY_TABLES_DIR": str(tables)})
    assert tables / "StreamingAssets" in roots.table_dirs
    assert tables / "Assetbundles" in roots.table_dirs


def test_table_root_given_as_bundle_dir_is_used_directly(tmp_path):
    root = make_tree(tmp_path)
    direct = tmp_path / "StreamingAssets"
    direct.mkdir()
    roots = resolve_roots(env={"CS_REVIVALSIDE_ROOT": str(root), "CS_GAMEPLAY_TABLES_DIR": str(direct)})
    assert direct in roots.table_dirs
    assert direct / "StreamingAssets" not in roots.table_dirs


def test_set_but_missing_revival_root_raises():
    with pytest.raises(DomainError) as err:
        resolve_roots(env={"CS_REVIVALSIDE_ROOT": "/nonexistent/revival"})
    assert "/nonexistent/revival" in str(err.value)


def test_unset_and_undiscoverable_revival_root_raises():
    with pytest.raises(DomainError) as err:
        resolve_roots(env={}, package_dir=Path("/nonexistent/deep/path"))
    assert "CS_REVIVALSIDE_ROOT" in str(err.value)


def test_sibling_revival_side_is_auto_discovered(tmp_path):
    """With no env var, a sibling RevivalSide/ next to the package is used."""
    root = make_tree(tmp_path / "RevivalSide")
    package_dir = tmp_path / "counterside-mcp" / "src" / "counterside_mcp"
    package_dir.mkdir(parents=True)
    roots = resolve_roots(env={}, package_dir=package_dir)
    assert roots.revival_root == root


def test_expand_root_uses_direct_bundle_layout(tmp_path):
    direct = tmp_path / "StreamingAssets"
    direct.mkdir()
    assert expand_root(direct) == (direct,)


def test_expand_root_adds_both_layouts(tmp_path):
    root = tmp_path / "gameplay-jsons"
    root.mkdir()
    assert expand_root(root) == (root / "Assetbundles", root / "StreamingAssets")


def test_health_reports_missing_asset_root(tmp_path):
    root = make_tree(tmp_path)
    roots = resolve_roots(env={"CS_REVIVALSIDE_ROOT": str(root)})
    report = health(roots)
    assert report["roots"]["asset"]["exists"] is True
    assert report["roots"]["table"]["exists"] is True


def test_health_reports_absent_asset_root_without_raising(tmp_path):
    root = make_tree(tmp_path)
    import shutil

    shutil.rmtree(root / "extracted-assets")
    roots = resolve_roots(env={"CS_REVIVALSIDE_ROOT": str(root)})
    report = health(roots)
    assert report["roots"]["asset"]["exists"] is False
    assert report["roots"]["asset"]["resolved"] is None
