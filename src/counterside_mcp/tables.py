"""Gameplay table discovery and reading.

Mirrors Mod:Side's ``modules/gameplay-jsons``: tables live under
``<root>/[Assetbundles|StreamingAssets]/<bundle>/luac/<NAME>.json``.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .config import Roots

_SUFFIX = re.compile(r"\.(json|luac|lua|bytes)$", re.IGNORECASE)
_TABLE_SUFFIXES = (".json", ".luac")
_SCHEMA_MAX_RECORDS = 40
_SCHEMA_MAX_DEPTH = 8


@dataclass(frozen=True)
class TableEntry:
    root: Path
    file_path: Path
    directory: str
    file_name: str
    relative_path: str
    extension: str
    table_name: str


def normalize_table_base_name(file_name: str) -> str:
    """Strip repeated .json/.luac/.lua/.bytes suffixes and any leading path."""
    value = str(file_name or "").replace("\\", "/").split("/")[-1]
    while _SUFFIX.search(value):
        value = _SUFFIX.sub("", value)
    return value


def parse_table_path(root: Path, file_path: Path) -> TableEntry | None:
    """Build a TableEntry, or None when the path is not a luac table path."""
    root = Path(root)
    file_path = Path(file_path)
    try:
        parts = [p for p in file_path.relative_to(root).as_posix().split("/") if p]
    except ValueError:
        return None
    if not parts:
        return None
    lowered = [p.lower() for p in parts]
    if "luac" not in lowered:
        return None
    index = lowered.index("luac")
    # The segment must not be first (no bundle) or last (no file name).
    if index <= 0 or index >= len(parts) - 1:
        return None
    file_name = parts[-1]
    extension = Path(file_name).suffix.lower()
    if extension not in _TABLE_SUFFIXES:
        return None
    return TableEntry(
        root=root,
        file_path=file_path,
        directory="/".join(parts[:index]),
        file_name=file_name,
        relative_path="/".join([*parts[:index], "luac", file_name]),
        extension=extension,
        table_name=normalize_table_base_name(file_name),
    )


def _walk(root: Path):
    if not root.exists():
        return
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_dir():
                stack.append(entry)
            elif entry.is_file() and entry.suffix.lower() in _TABLE_SUFFIXES:
                yield entry


def list_table_entries(roots: Roots) -> list[TableEntry]:
    """Every discoverable table, deduped per directory+name with .json preferred."""
    found: dict[str, TableEntry] = {}
    for root in roots.table_dirs:
        for file_path in _walk(root):
            entry = parse_table_path(root, file_path)
            if entry is None:
                continue
            key = f"{entry.directory.lower()}/{entry.table_name.lower()}"
            existing = found.get(key)
            if existing is None or (entry.extension == ".json" and existing.extension != ".json"):
                found[key] = entry
    return sorted(found.values(), key=lambda e: e.relative_path)


def find_table_entry(roots: Roots, directory: str, file_name: str) -> TableEntry | None:
    table_name = normalize_table_base_name(file_name).lower()
    directory = str(directory or "").replace("\\", "/").strip("/")
    for entry in list_table_entries(roots):
        if entry.directory == directory and entry.table_name.lower() == table_name:
            return entry
    return None


def read_table(entry: TableEntry):
    """Parse a table file, or None when it is missing or undecodable."""
    try:
        with entry.file_path.open(encoding="utf-8") as handle:
            parsed = json.load(handle)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return parsed if isinstance(parsed, (dict, list)) else None


def extract_table_records(parsed) -> list:
    """Handle a bare array, {records:[]}, {root:[]}, or a keyed root object."""
    if isinstance(parsed, list):
        return parsed
    if not isinstance(parsed, dict):
        return []
    if isinstance(parsed.get("records"), list):
        return parsed["records"]
    if isinstance(parsed.get("root"), list):
        return parsed["root"]
    root = parsed.get("root")
    if isinstance(root, dict):
        records = []
        for key, value in root.items():
            if isinstance(value, list):
                records.append({"__key": key, "values": value})
            elif isinstance(value, dict):
                records.append({"__key": key, **value})
            else:
                records.append({"__key": key, "value": value})
        return records
    return []


def read_table_records(roots: Roots, directory: str, file_name: str) -> tuple[list, dict]:
    """Records plus a small metadata dict. Missing tables return ([], found=False)."""
    entry = find_table_entry(roots, directory, file_name)
    if entry is None:
        return [], {"found": False}
    parsed = read_table(entry)
    records = extract_table_records(parsed)
    if not records and isinstance(parsed, dict):
        # A decoded table that is a single object describes one record.
        records = [parsed]
    return records, {"found": True, "entry": table_entry_json(entry)}


def _collect(value, prefix: str, fields: dict, depth: int) -> None:
    if depth > _SCHEMA_MAX_DEPTH or value is None:
        return
    if isinstance(value, list):
        for item in value[:3]:
            _collect(item, f"{prefix}[]", fields, depth + 1)
        return
    if isinstance(value, dict):
        for key, child in value.items():
            _collect(child, f"{prefix}.{key}" if prefix else key, fields, depth + 1)
        return
    if not prefix or prefix in fields:
        return
    fields[prefix] = {"path": prefix, "type": type(value).__name__, "example": value}


def table_schema(records: list) -> list[dict]:
    """Flatten sampled records into field paths, types and an example value."""
    fields: dict[str, dict] = {}
    for record in records[:_SCHEMA_MAX_RECORDS]:
        _collect(record, "", fields, 0)
    return list(fields.values())


def table_entry_json(entry: TableEntry) -> dict:
    return {
        "directory": entry.directory,
        "fileName": entry.file_name,
        "tableName": entry.table_name,
        "relativePath": entry.relative_path,
        "extension": entry.extension,
    }
