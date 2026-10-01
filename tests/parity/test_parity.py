"""Compare this server's output against the live Node Mod:Side API.

These tests are the reason the port can be trusted at all: they assert that
the Python reader and the Node reader describe the same data, rather than
asserting that the Python reader matches whatever it happened to produce.
Run them with Mod:Side up; they skip otherwise.
"""

import pytest

from counterside_mcp import assets as assets_module
from counterside_mcp import objects as objects_module
from counterside_mcp import systems as systems_module
from counterside_mcp import tables as tables_module
from counterside_mcp.config import resolve_roots

pytestmark = pytest.mark.parity


@pytest.fixture(scope="module")
def roots():
    return resolve_roots()


def test_systems_parity(node_api, roots):
    theirs = node_api("systems")
    ours = systems_module.list_systems(roots)
    assert [system["id"] for system in ours["systems"]] == [
        system["id"] for system in theirs["systems"]
    ]


def test_table_count_parity(node_api, roots):
    theirs = node_api("tables", limit=1)
    ours = tables_module.list_table_entries(roots)
    assert len(ours) == theirs["total"]


def test_asset_listing_parity(node_api, roots):
    theirs = node_api("assets", path="Data/StreamingAssets", limit=250)
    ours = assets_module.list_directory(roots, "Data/StreamingAssets", "", 0, 250)
    assert [entry["name"] for entry in ours["entries"]] == [
        entry["name"] for entry in theirs["entries"]
    ]
    assert ours["total"] == theirs["total"]


@pytest.mark.parametrize("object_type", ["unit", "ship", "operator", "gear"])
def test_object_total_parity(node_api, roots, object_type):
    theirs = node_api("objects", type=object_type, limit=1)
    ours = objects_module.list_objects(roots, object_type, "", 0, 1)
    assert ours["total"] == theirs["total"]


def test_ship_listing_parity(node_api, roots):
    """Names and ids in order, not just the count."""
    theirs = node_api("objects", type="ship", limit=250)
    ours = objects_module.list_objects(roots, "ship", "", 0, 250)
    key = lambda row: (row["id"], row["strId"])
    assert [key(row) for row in ours["objects"]] == [key(row) for row in theirs["objects"]]


def test_object_inspection_parity(node_api, roots):
    """Every referenced id field must come back with the same value.

    This is the assertion that would catch the gear-icon prefix divergence:
    the icon field resolves to a path on one side and an empty string on the
    other.
    """
    theirs = node_api("object", type="gear", id=90001)
    ours = objects_module.get_object(roots, "gear", 90001)
    key = lambda entry: (entry["field"], str(entry["value"]))
    assert sorted(key(entry) for entry in ours["ids"]) == sorted(
        key(entry) for entry in theirs["ids"]
    )


def test_table_records_parity(node_api, roots):
    theirs = node_api("table", directory="ab_script_unit_data", file="LUA_UNIT_TEMPLET_BASE")
    ours, _ = tables_module.read_table_records(roots, "ab_script_unit_data", "LUA_UNIT_TEMPLET_BASE")
    assert len(ours) == theirs["total"]
