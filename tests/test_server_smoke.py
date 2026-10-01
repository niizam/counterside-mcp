import asyncio
import json
from pathlib import Path

import pytest

from counterside_mcp import server


def build_tree(tmp_path: Path) -> Path:
    luac = tmp_path / "gameplay-jsons" / "StreamingAssets" / "ab_script_unit_data" / "luac"
    luac.mkdir(parents=True)
    (luac / "LUA_UNIT_TEMPLET_BASE.json").write_text(json.dumps({"records": [{
        "m_UnitID": 1, "m_UnitStrID": "NKM_UNIT_A", "m_NKM_UNIT_TYPE": "NUT_COUNTER",
        "m_Name": "NAME_A",
    }]}))
    icons = (
        tmp_path / "extracted-assets" / "all" / "Data" / "StreamingAssets"
        / "ab_inven_icon_unit" / "Texture2D"
    )
    icons.mkdir(parents=True)
    (icons / "ICON_A.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (icons / "notes.txt").write_text("plain text")
    (tmp_path / "wiki" / "data").mkdir(parents=True)
    (tmp_path / "server-data").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def roots(monkeypatch, tmp_path):
    root = build_tree(tmp_path)
    monkeypatch.setenv("CS_REVIVALSIDE_ROOT", str(root))
    # The resolver memoizes, and each test builds a fresh tree. Clear only the
    # real lru-wrapped function, then pin the result so every call site sees it.
    server.resolve.cache_clear()
    resolved = server.resolve()
    server.resolve.cache_clear()
    monkeypatch.setattr(server, "resolve", lambda: resolved)
    return resolved


def test_health_reports_roots(roots):
    report = server.health_report(roots)
    assert report["roots"]["asset"]["exists"] is True
    assert report["version"]


def test_list_objects_and_asset_listing(roots):
    objects = server.list_objects(roots, "unit", "", 0, 100)
    assert objects["total"] == 1
    listing = server.list_directory(roots, "", "", 0, 50)
    assert listing["total"] >= 1


def test_tools_and_resources_are_registered():
    names = sorted(tool.name for tool in asyncio.run(server.mcp.list_tools()))
    assert len(names) == 13, names
    assert all(name.startswith("counterside_") for name in names)
    # Three parameterised templates, plus the fixed counterside://systems URI.
    templates = asyncio.run(server.mcp.list_resource_templates())
    assert len(templates) == 3
    resources = asyncio.run(server.mcp.list_resources())
    assert [str(resource.uri) for resource in resources] == ["counterside://systems"]


def test_tool_errors_surface_as_tool_errors(roots):
    from mcp.server.mcpserver.exceptions import ToolError

    with pytest.raises(ToolError):
        server.counterside_list_objects("weapon")


def test_get_asset_returns_a_real_image_block(roots):
    """A dict {'type': 'image'} block converts to text and drops the bytes, so
    the image must be returned as an Image content block. The SDK converts it
    on the way out — assert the wire form, not the wrapper."""
    from mcp.server.mcpserver import Image as SDKImage
    from mcp.server.mcpserver.utilities.func_metadata import _convert_to_content
    from mcp.types import ImageContent, TextContent

    blocks = server.counterside_get_asset(
        "Data/StreamingAssets/ab_inven_icon_unit/Texture2D/ICON_A.png"
    )
    assert isinstance(blocks[0], TextContent)
    assert isinstance(blocks[1], SDKImage)

    converted = _convert_to_content(blocks)
    assert [type(block).__name__ for block in converted] == ["TextContent", "ImageContent"]
    image = converted[1]
    assert isinstance(image, ImageContent)
    assert image.mime_type == "image/png"
    assert image.data


def test_non_image_asset_returns_text_only(roots):
    from mcp.types import TextContent

    blocks = server.counterside_get_asset(
        "Data/StreamingAssets/ab_inven_icon_unit/Texture2D/notes.txt"
    )
    assert len(blocks) == 1
    assert isinstance(blocks[0], TextContent)
