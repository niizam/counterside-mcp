"""MCP server: registers read-only tools and resources over stdio.

Every tool here reads. Nothing in this package writes, patches or builds, so
there is no authoring surface to lock down — the guard exists only to turn a
domain failure into a message the model can act on instead of a traceback.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from mcp.server import MCPServer
from mcp.server.mcpserver import Image
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import TextContent

from . import __version__
from . import assets as assets_module
from . import config as config_module
from . import objects as objects_module
from . import systems as systems_module
from . import tables as tables_module
from .errors import DomainError

# The package sits at <repo>/src/counterside_mcp, so the sibling RevivalSide/
# check in config.resolve_roots starts from the repo root above it.
PACKAGE_DIR = Path(__file__).resolve().parent.parent

mcp = MCPServer("counterside")


@lru_cache(maxsize=1)
def resolve() -> config_module.Roots:
    return config_module.resolve_roots(package_dir=PACKAGE_DIR)


def _roots() -> config_module.Roots:
    return resolve()


def _guard(fn, *args, **kwargs):
    """Run a reader, reporting a domain failure as a tool error."""
    try:
        return fn(*args, **kwargs)
    except DomainError as error:
        raise ToolError(str(error)) from error
    except ValueError as error:
        raise ToolError(str(error)) from error


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _page(offset, limit, default: int = 100) -> tuple[int, int]:
    """Clamp a page request the same way the asset and table readers do."""
    offset = max(0, int(offset or 0))
    limit = max(1, min(250, int(limit or default)))
    return offset, limit


# --- Pure, testable cores --------------------------------------------------
# The registered tools are thin wrappers so that the logic can be called
# directly in tests without going through the MCP transport.


def health_report(roots: config_module.Roots) -> dict:
    report = config_module.health(roots)
    report["tableCount"] = len(tables_module.list_table_entries(roots))
    report["systemsCount"] = len(systems_module.list_systems(roots)["systems"])
    report["version"] = __version__
    return report


def list_objects(roots, object_type="unit", query: str = "", offset: int = 0, limit: int = 100) -> dict:
    return objects_module.list_objects(roots, object_type, query, offset, limit)


def list_directory(roots, path: str = "", query: str = "", offset: int = 0, limit: int = 100) -> dict:
    return assets_module.list_directory(roots, path, query, offset, limit)


def get_asset(roots, path: str) -> list:
    """Metadata, plus the image itself when the file is a browser-viewable one."""
    metadata = _guard(assets_module.asset_metadata, roots, path)
    text = TextContent(type="text", text=_json(metadata))
    if not metadata["isImage"]:
        return [text]

    data, content_type = assets_module.asset_bytes(roots, path)
    # A dict {"type": "image"} block would be converted to a text block and the
    # bytes silently dropped, so the image has to be an Image content block.
    fmt = content_type.removeprefix("image/").replace("jpg", "jpeg")
    return [text, Image(data=data, format=fmt)]


# --- Discovery -------------------------------------------------------------


@mcp.tool()
def counterside_health() -> dict:
    """Report the resolved data roots, table and system counts, and version.

    Call this first: it says whether the gameplay tables, the extracted assets
    and the wiki index were all found, and warns when only half the data is
    reachable.
    """
    return health_report(_roots())


@mcp.tool()
def counterside_list_systems() -> dict:
    """List the curated CounterSide game systems with their tables and edit hints."""
    return _guard(systems_module.list_systems, _roots())


@mcp.tool()
def counterside_search_fields(query: str) -> dict:
    """Find where a concept lives: gameplay systems, tables and fields.

    Search by intent, not by table name — "unit respawn cost" or "gear
    potential option" work better than guessing an identifier.
    """
    return _guard(systems_module.search_fields, _roots(), query)


# --- Table text ------------------------------------------------------------


@mcp.tool()
def counterside_list_tables(query: str = "", offset: int = 0, limit: int = 100) -> dict:
    """List the decoded gameplay tables, optionally filtered by a name substring."""
    entries = tables_module.list_table_entries(_roots())
    needle = str(query or "").strip().lower()
    if needle:
        entries = [
            entry
            for entry in entries
            if needle in entry.table_name.lower() or needle in entry.directory.lower()
        ]
    offset, limit = _page(offset, limit)
    return {
        "total": len(entries),
        "offset": offset,
        "limit": limit,
        "tables": [tables_module.table_entry_json(e) for e in entries[offset : offset + limit]],
    }


@mcp.tool()
def counterside_get_table(
    directory: str, file: str, query: str = "", offset: int = 0, limit: int = 100
) -> dict:
    """Read one gameplay table's records, optionally filtered by a substring.

    Large tables run to tens of thousands of rows; pass query to narrow, and
    page with offset and limit.
    """
    roots = _roots()
    entry = tables_module.find_table_entry(roots, directory, file)
    if entry is None:
        raise ToolError(f"Gameplay table was not found: {directory}/{file}")
    records, _ = tables_module.read_table_records(roots, directory, file)
    unfiltered_total = len(records)
    needle = str(query or "").strip().lower()
    if needle:
        records = [r for r in records if needle in json.dumps(r, ensure_ascii=False).lower()]
    offset, limit = _page(offset, limit)
    return {
        "table": tables_module.table_entry_json(entry),
        "total": len(records),
        "unfilteredTotal": unfiltered_total,
        "offset": offset,
        "limit": limit,
        "records": records[offset : offset + limit],
    }


# --- Game objects ----------------------------------------------------------


@mcp.tool()
def counterside_list_objects(
    type: str = "unit", query: str = "", offset: int = 0, limit: int = 100
) -> dict:
    """List game objects by type: unit, ship, operator or gear."""
    return _guard(objects_module.list_objects, _roots(), type, query, offset, limit)


@mcp.tool()
def counterside_get_object(type: str, id: int) -> dict:
    """Inspect one object: its ids, every id it references, stats, and asset paths.

    This is the entry point for "what is this thing and what does it link to" —
    skills, skins, stat ranges, and the asset fields that resolve to real files.
    """
    return _guard(objects_module.get_object, _roots(), type, id)


@mcp.tool()
def counterside_find_asset_for_object(type: str, id: int, field: str = "") -> dict:
    """Resolve an object's asset fields to concrete paths in the asset tree."""
    return _guard(objects_module.find_asset_for_object, _roots(), type, id, field or None)


# --- Extracted assets ------------------------------------------------------


@mcp.tool()
def counterside_list_assets(path: str = "", query: str = "", offset: int = 0, limit: int = 100) -> dict:
    """List a directory of the extracted-asset tree with typed entries.

    Paths are relative to the asset root, for example "Data/StreamingAssets".
    """
    return _guard(assets_module.list_directory, _roots(), path, query, offset, limit)


@mcp.tool()
def counterside_get_asset(path: str) -> list:
    """Return a file's metadata, and the image itself when it is a PNG/JPEG.

    Use this to actually look at a sprite or icon rather than guessing from a name.
    """
    return _guard(get_asset, _roots(), path)


@mcp.tool()
def counterside_read_text(path: str, maxBytes: int = 524288) -> dict:
    """Read a capped text preview of a text-like asset (json, atlas, csv, txt, ...)."""
    return _guard(assets_module.text_preview, _roots(), path, maxBytes)


@mcp.tool()
def counterside_get_spine_set(path: str) -> dict:
    """Resolve a Spine source file to its skeleton, atlas and texture pages."""
    return _guard(assets_module.spine_set, _roots(), path)


@mcp.tool()
def counterside_find_related(path: str) -> dict:
    """Find an asset's siblings and the gameplay tables that reference it.

    This is the bridge from an image on disk back to the data that names it.
    """
    return _guard(assets_module.find_related, _roots(), path)


# --- Resources -------------------------------------------------------------


@mcp.resource("counterside://systems")
def resource_systems() -> str:
    """Every curated game system."""
    return _json(systems_module.list_systems(_roots()))


@mcp.resource("counterside://table/{directory}/{file}")
def resource_table(directory: str, file: str) -> str:
    """One gameplay table's records."""
    return _json(counterside_get_table(directory, file))


@mcp.resource("counterside://object/{type}/{id}")
def resource_object(type: str, id: int) -> str:
    """One game object inspection."""
    return _json(counterside_get_object(type, id))


@mcp.resource("counterside://asset/{+path}")
def resource_asset(path: str) -> str:
    """Text preview of one asset."""
    return _json(counterside_read_text(path))


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
