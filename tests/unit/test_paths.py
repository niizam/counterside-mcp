from pathlib import Path

import pytest

from counterside_mcp.errors import DomainError
from counterside_mcp.paths import (
    is_inside,
    normalize_relative_path,
    resolve_existing,
    resolve_existing_dir,
)


def test_normalize_converts_backslashes_and_collapses():
    assert normalize_relative_path("a\\b\\..\\c") == "a/c"
    assert normalize_relative_path("/leading/slash") == "leading/slash"


@pytest.mark.parametrize("value", ["../escape", "a/../../escape", "/etc/passwd", "C:/Windows/system32"])
def test_escape_paths_are_rejected(tmp_path, value):
    (tmp_path / "inside.txt").write_text("x")
    with pytest.raises(DomainError) as err:
        resolve_existing(tmp_path, value)
    assert "outside" in str(err.value).lower()


def test_interior_parent_segment_is_allowed(tmp_path):
    """'..' that stays inside the root is normal, not an attack."""
    target = tmp_path / "Data" / "a.png"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"x")
    assert resolve_existing(tmp_path, "Data/sub/../a.png") == target


def test_resolve_existing_rejects_absolute_but_existing_path(tmp_path):
    """An absolute path to a real file outside the root must still be refused."""
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("x")
    with pytest.raises(DomainError) as err:
        resolve_existing(tmp_path, str(outside))
    assert "outside" in str(err.value).lower()


def test_resolve_existing_returns_path_for_real_file(tmp_path):
    target = tmp_path / "Data" / "a.png"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"x")
    assert resolve_existing(tmp_path, "Data/a.png") == target


def test_resolve_existing_dir_rejects_a_file(tmp_path):
    (tmp_path / "f.txt").write_text("x")
    with pytest.raises(DomainError):
        resolve_existing_dir(tmp_path, "f.txt")


def test_is_inside(tmp_path):
    assert is_inside(tmp_path, tmp_path / "a" / "b")
    assert not is_inside(tmp_path, tmp_path.parent / "elsewhere")
