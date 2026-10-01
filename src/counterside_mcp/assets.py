"""Reading the extracted asset tree.

A port of Mod:Side's asset endpoints (``server/assetViewer.js``): directory
listing, file metadata and bytes, text previews, Spine set resolution, and the
relation search that ties an asset back to gameplay tables.
"""

import json
import os
import re
from functools import lru_cache
from pathlib import Path, PurePosixPath

from .config import Roots
from .errors import DomainError
from .paths import is_inside, normalize_relative_path, resolve_existing, resolve_existing_dir
from .stats import TEXT_EXTENSIONS, asset_type_for, normalize_relation_value

DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 250
DEFAULT_TEXT_PREVIEW_BYTES = 512 * 1024
MAX_RELATED_RESULTS = 40

CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".json": "application/json",
    ".txt": "text/plain; charset=utf-8",
    ".atlas": "text/plain; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".log": "text/plain; charset=utf-8",
    ".lua": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".xml": "application/xml",
    ".yaml": "text/yaml; charset=utf-8",
    ".yml": "text/yaml; charset=utf-8",
    ".wav": "audio/wav",
    ".skel": "application/octet-stream",
    ".bytes": "application/octet-stream",
}

_UNITY_RESOURCE_TYPES = {"AudioClip", "Sprite", "TextAsset", "Texture2D"}


def _asset_root(roots: Roots) -> Path:
    for candidate in roots.asset_dirs:
        if candidate.exists():
            return Path(candidate)
    return Path(roots.asset_dirs[0])


def _page(offset, limit) -> tuple[int, int]:
    offset = max(0, int(_int(offset) or 0))
    limit = max(1, min(MAX_PAGE_SIZE, int(_int(limit) or DEFAULT_PAGE_SIZE)))
    return offset, limit


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _relative(root: Path, file_path: Path) -> str:
    """The asset-relative path, with both sides resolved so links cannot fake it."""
    try:
        return normalize_relative_path(
            Path(os.path.realpath(file_path)).relative_to(os.path.realpath(root)).as_posix()
        )
    except (ValueError, OSError):
        return normalize_relative_path(str(file_path))


def _content_type(file_path: Path) -> str:
    return CONTENT_TYPES.get(file_path.suffix.lower(), "application/octet-stream")


# --------------------------------------------------------------------------
# Directory and file reading
# --------------------------------------------------------------------------


def list_directory(
    roots: Roots, path: str = "", query: str = "", offset: int = 0, limit: int = 100
) -> dict:
    root = _asset_root(roots)
    relative = normalize_relative_path(path)
    directory = resolve_existing_dir(root, relative) if relative else root
    needle = str(query or "").strip().lower()
    entries = []
    try:
        children = list(directory.iterdir())
    except OSError as error:
        raise DomainError(f"Asset directory could not be read: {relative}") from error
    for child in children:
        if child.is_symlink() or not (child.is_dir() or child.is_file()):
            continue
        if needle and needle not in child.name.lower():
            continue
        child_relative = normalize_relative_path(f"{relative}/{child.name}" if relative else child.name)
        entry = {
            "name": child.name,
            "path": child_relative,
            "kind": "directory" if child.is_dir() else "file",
        }
        if child.is_file():
            try:
                entry["size"] = child.stat().st_size
            except OSError:
                entry["size"] = 0
            entry["extension"] = child.suffix.lower()
            entry["assetType"] = asset_type_for(child_relative, entry["extension"])
        entries.append(entry)
    entries.sort(key=lambda item: (item["kind"] != "directory", item["name"].lower()))
    offset, limit = _page(offset, limit)
    return {
        "path": relative,
        "parentPath": normalize_relative_path(str(PurePosixPath(relative).parent)) if relative else None,
        "total": len(entries),
        "offset": offset,
        "limit": limit,
        "entries": entries[offset : offset + limit],
    }


def asset_metadata(roots: Roots, path: str) -> dict:
    root = _asset_root(roots)
    relative = normalize_relative_path(path)
    file_path = resolve_existing(root, relative)
    if not file_path.is_file():
        raise DomainError(f"Asset path is not a file: {relative}")
    extension = file_path.suffix.lower()
    return {
        "path": relative,
        "name": file_path.name,
        "size": file_path.stat().st_size,
        "extension": extension,
        "assetType": asset_type_for(relative, extension),
        "contentType": _content_type(file_path),
        "isImage": extension in {".png", ".jpg", ".jpeg", ".webp"},
    }


def asset_bytes(roots: Roots, path: str) -> tuple[bytes, str]:
    """The file's bytes and its content type. Read-only: nothing is written."""
    metadata = asset_metadata(roots, path)
    file_path = resolve_existing(_asset_root(roots), metadata["path"])
    return file_path.read_bytes(), metadata["contentType"]


def text_preview(roots: Roots, path: str, max_bytes: int = DEFAULT_TEXT_PREVIEW_BYTES) -> dict:
    root = _asset_root(roots)
    relative = normalize_relative_path(path)
    file_path = resolve_existing(root, relative)
    if not file_path.is_file():
        raise DomainError(f"Asset path is not a file: {relative}")
    extension = file_path.suffix.lower()
    if extension not in TEXT_EXTENSIONS:
        raise DomainError(
            f"This asset does not have a text preview: {extension or 'extensionless file'}",
            status=415,
        )
    size = file_path.stat().st_size
    cap = max(1, _int(max_bytes) or DEFAULT_TEXT_PREVIEW_BYTES)
    with file_path.open("rb") as handle:
        data = handle.read(cap)
    return {
        "path": relative,
        "size": size,
        "truncated": size > len(data),
        "text": data.decode("utf-8", errors="replace"),
    }


# --------------------------------------------------------------------------
# Spine sets
# --------------------------------------------------------------------------


def _is_spine_skeleton(file_path: Path) -> bool:
    if file_path.suffix.lower() == ".skel":
        return True
    if file_path.suffix.lower() not in (".json", ".bytes"):
        return False
    try:
        text = file_path.read_text(encoding="utf-8-sig").lstrip()
    except (OSError, UnicodeDecodeError):
        return False
    if not text.startswith("{"):
        return False
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return False
    return bool(
        isinstance(parsed, dict)
        and parsed.get("skeleton")
        and (parsed.get("bones") or parsed.get("slots") or parsed.get("animations"))
    )


def _atlas_pages(atlas_path: Path) -> list[str]:
    try:
        text = atlas_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    pages: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if line and ":" not in line and line.lower().endswith(".png") and line not in pages:
            pages.append(line)
    return pages


def _find_files_by_name(root: Path, names) -> dict[str, Path]:
    """The first file matching each wanted name, anywhere under root."""
    wanted = {str(name).lower() for name in names}
    found: dict[str, Path] = {}
    stack = [root]
    while stack and len(found) < len(wanted):
        current = stack.pop()
        try:
            children = list(current.iterdir())
        except OSError:
            continue
        for child in children:
            if child.is_symlink():
                continue
            if child.is_dir():
                stack.append(child)
            elif child.is_file():
                lowered = child.name.lower()
                if lowered in wanted:
                    found.setdefault(lowered, child)
    return found


def _spine_skeleton_name(file_path: Path) -> str:
    if file_path.suffix.lower() == ".bytes":
        return f"{file_path.stem}.json"
    return file_path.name


def spine_set(roots: Roots, path: str) -> dict:
    """Every file a Spine viewer needs for one skeleton: skel, atlas, textures."""
    root = _asset_root(roots)
    relative = normalize_relative_path(path)
    selected = resolve_existing(root, relative)
    if not selected.is_file():
        raise DomainError(f"Spine asset path is not a file: {relative}")
    extension = selected.suffix.lower()
    if extension not in (".atlas", ".bytes", ".json", ".skel"):
        raise DomainError("This asset is not a Spine source file.", status=415)
    if extension in (".bytes", ".json") and not _is_spine_skeleton(selected):
        return {"ready": False, "notSpine": True, "missing": []}

    text_asset_dir = selected.parent
    if text_asset_dir.name.lower() != "textasset":
        return {"ready": False, "missing": ["Spine TextAsset folder"]}

    source_files = [child for child in text_asset_dir.iterdir() if child.is_file()]
    base_name = selected.stem
    atlas_files = [child for child in source_files if child.suffix.lower() == ".atlas"]
    exact_atlas = next(
        (child for child in atlas_files if child.stem.lower() == base_name.lower()), None
    )
    atlas_path = (
        selected if extension == ".atlas" else (exact_atlas or (atlas_files[0] if len(atlas_files) == 1 else None))
    )
    if atlas_path is None:
        return {"ready": False, "missing": ["matching .atlas"]}

    atlas_base = atlas_path.stem.lower()
    skeletons = [child for child in source_files if _is_spine_skeleton(child)]
    if len(atlas_files) > 1:
        skeletons = [
            child
            for child in skeletons
            if child == selected or child.stem.lower() == atlas_base
        ]
    if _is_spine_skeleton(selected) and selected not in skeletons:
        skeletons.insert(0, selected)
    if not skeletons:
        return {"ready": False, "missing": ["matching .skel or Spine JSON"]}

    page_names = _atlas_pages(atlas_path)
    if not page_names:
        return {"ready": False, "missing": ["atlas PNG page"]}
    png_files = _find_files_by_name(text_asset_dir.parent, page_names)
    missing = [name for name in page_names if name.lower() not in png_files]
    if missing:
        return {"ready": False, "missing": [f"atlas page {name}" for name in missing]}

    return {
        "ready": True,
        "files": [
            {"path": _relative(root, skeleton), "name": _spine_skeleton_name(skeleton), "role": "skeleton"}
            for skeleton in skeletons
        ]
        + [{"path": _relative(root, atlas_path), "name": atlas_path.name, "role": "atlas"}]
        + [
            {"path": _relative(root, png_files[name.lower()]), "name": name, "role": "texture"}
            for name in page_names
        ],
    }


# --------------------------------------------------------------------------
# Related assets and tables
# --------------------------------------------------------------------------


@lru_cache(maxsize=4)
def _read_id_index(index_path: Path) -> tuple:
    """The wiki ID index of every table record, or empty when absent.

    Read once and kept as a tuple: it is tens of megabytes, and the relation
    search would otherwise re-parse it on every call.
    """
    try:
        rows = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return ()
    return tuple(row for row in rows if isinstance(row, dict)) if isinstance(rows, list) else ()


@lru_cache(maxsize=8)
def _read_object_index(index_path: Path) -> tuple:
    try:
        parsed = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return ()
    objects = parsed.get("objects") if isinstance(parsed, dict) else None
    return tuple(item for item in objects if isinstance(item, dict)) if isinstance(objects, list) else ()


def _collect_relation_values(value, key, terms: set, ids: set, path_ids: set, depth: int = 0) -> None:
    """Walk a decoded Unity document for referenced ids, path ids and names."""
    if depth > 12 or value is None:
        return
    if isinstance(value, list):
        for item in value:
            _collect_relation_values(item, key, terms, ids, path_ids, depth + 1)
        return
    if isinstance(value, dict):
        path_id = value.get("m_PathID")
        if path_id is not None and not _int(value.get("m_FileID")) and _int(path_id):
            path_ids.add(str(path_id))
        for child_key, child_value in value.items():
            _collect_relation_values(child_value, child_key, terms, ids, path_ids, depth + 1)
        return
    if _RELATION_ID_KEY.search(str(key)):
        return
    relevant_key = bool(_RELATION_KEY.search(str(key)))
    if isinstance(value, bool):
        return
    # Not a float: upstream only takes safe integers, so 12.5 is skipped whole.
    if isinstance(value, int):
        if relevant_key and abs(value) >= 10:
            ids.add(str(value))
        return
    if isinstance(value, str) and (relevant_key or _SHOUTY_NAME.match(value)):
        _add_relation_term(terms, value)


_RELATION_ID_KEY = re.compile(r"pathid|fileid", re.IGNORECASE)
_RELATION_KEY = re.compile(
    r"id|name|str|key|asset|icon|prefab|resource|texture|sprite|audio|stage|unit|item|episode|dungeon",
    re.IGNORECASE,
)
# Upstream flags this one too, so any four-letter word counts as a candidate
# term — matching their behaviour matters more than the name suggesting caps.
_SHOUTY_NAME = re.compile(r"^[A-Z][A-Z0-9_./-]{3,}$", re.IGNORECASE)


def _add_relation_term(terms: set, value) -> None:
    text = str(value or "").strip()
    if len(text) < 3 or len(text) > 180 or len(terms) >= 48:
        return
    terms.add(text)
    base_name = PurePosixPath(text).stem
    if base_name != text and len(base_name) >= 3:
        terms.add(base_name)


def _bundle_root(roots: Roots, file_path: Path) -> Path | None:
    """The asset bundle that holds this file.

    A Mod:Side export marks bundles with ObjectIndex/objects.json; an extracted
    tree marks them with manifest.json. Both are preferred over the upstream
    depth-2 fallback, which for a Data/StreamingAssets/<bundle> layout resolves
    to the container directory — 6000 bundles and 67k files — and turns the
    related-name scan that follows into a full-tree walk.
    """
    for root in roots.asset_dirs:
        root = Path(root)
        if not is_inside(root, file_path):
            continue
        current = file_path.parent
        while is_inside(root, current):
            if (current / "ObjectIndex" / "objects.json").exists():
                return current
            if current == root:
                break
            current = current.parent
        current = file_path.parent
        while is_inside(root, current) and current != root:
            if (current / "manifest.json").exists():
                return current
            current = current.parent
        parts = normalize_relative_path(_relative(root, file_path)).split("/")
        if len(parts) >= 3:
            candidate = root / parts[0] / parts[1]
            if candidate.is_dir():
                return candidate
    return None


def _find_object_file(bundle_root: Path, unity_object: dict) -> Path | None:
    name = unity_object.get("name")
    if not name:
        return None
    wanted = normalize_relation_value(name)
    object_type = unity_object.get("type")
    for directory in (
        bundle_root / "TypeTree" / str(object_type),
        bundle_root / str(object_type),
        bundle_root / f"{object_type}Meta",
    ):
        try:
            children = list(directory.iterdir())
        except OSError:
            continue
        for child in children:
            if child.is_file() and normalize_relation_value(child.stem) == wanted:
                return child
    return None


def _find_bundle_files(bundle_root: Path, predicate):
    found: list[Path] = []
    stack = [bundle_root]
    while stack and len(found) < MAX_RELATED_RESULTS:
        current = stack.pop()
        try:
            # scandir reports the entry type from the directory read itself.
            # Three pathlib stat calls per child are painfully slow on the
            # Windows mount this tree usually lives on, and answer no better.
            entries = list(os.scandir(current))
        except OSError:
            continue
        for entry in entries:
            if entry.name == "ObjectIndex":
                continue
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir():
                    stack.append(Path(entry.path))
                elif entry.is_file() and predicate(Path(entry.path)):
                    found.append(Path(entry.path))
            except OSError:
                continue
    return found


def _add_related_file(files: list, seen: set, root: Path, file_path: Path, relation: str) -> None:
    try:
        real = Path(os.path.realpath(file_path))
    except OSError:
        return
    key = str(real)
    if key in seen or len(files) >= MAX_RELATED_RESULTS:
        return
    seen.add(key)
    extension = real.suffix.lower()
    relative = _relative(root, real)
    try:
        size = real.stat().st_size
    except OSError:
        size = 0
    files.append(
        {
            "name": real.name,
            "path": relative,
            "kind": "file",
            "extension": extension,
            "size": size,
            "assetType": asset_type_for(relative, extension),
            "relation": relation,
        }
    )


def _find_related_tables(index_rows: tuple, terms: set, ids: set) -> list[dict]:
    normalized = [normalize_relation_value(term) for term in terms]
    normalized = [term for term in normalized if len(term) >= 3]
    matches: list[dict] = []
    seen: set[str] = set()
    for row in index_rows:
        matched_by = ""
        if str(row.get("id")) in ids:
            matched_by = f"{row.get('idField') or 'ID'} {row.get('id')}"
        if not matched_by:
            for field in ("strId", "image", "name", "type"):
                raw = row.get(field)
                # Most rows leave several of these empty, and normalizing each
                # one costs two passes over a 260k-row index.
                if not raw:
                    continue
                value = normalize_relation_value(raw)
                if not value:
                    continue
                hit = next(
                    (
                        term
                        for term in normalized
                        if value == term
                        or (
                            len(term) >= 8
                            and len(value) >= 8
                            and (value.endswith(term) or term.endswith(value))
                        )
                    ),
                    None,
                )
                if hit:
                    matched_by = f"{field} {raw}"
                    break
        if not matched_by:
            continue
        key = f"{row.get('source') or row.get('table')}|{row.get('id')}|{row.get('strId') or ''}"
        if key in seen:
            continue
        seen.add(key)
        matches.append({**row, "matchedBy": matched_by})
        if len(matches) >= MAX_RELATED_RESULTS:
            break
    return matches


def find_related(roots: Roots, path: str) -> dict:
    """Assets and gameplay tables that share an identity with this asset."""
    root = _asset_root(roots)
    relative = normalize_relative_path(path)
    selected = resolve_existing(root, relative)
    if not selected.is_file():
        raise DomainError(f"Asset path is not a file: {relative}")

    terms: set[str] = set()
    ids: set[str] = set()
    path_ids: set[str] = set()
    _add_relation_term(terms, selected.stem)
    if selected.suffix.lower() == ".json" and selected.stat().st_size <= DEFAULT_TEXT_PREVIEW_BYTES:
        try:
            _collect_relation_values(json.loads(selected.read_text(encoding="utf-8")), "", terms, ids, path_ids)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            pass

    bundle_root = _bundle_root(roots, selected)
    objects_by_path_id: dict[str, dict] = {}
    if bundle_root is not None:
        objects_by_path_id = {
            str(item["path_id"]): item
            for item in _read_object_index(bundle_root / "ObjectIndex" / "objects.json")
            if item.get("path_id") is not None
        }

    files: list[dict] = []
    unity_objects: list[dict] = []
    try:
        seen = {os.path.realpath(selected)}
    except OSError:
        seen = {str(selected)}
    selected_stem = normalize_relation_value(selected.stem)

    if bundle_root is not None and selected_stem:
        for match in _find_bundle_files(
            bundle_root, lambda child: normalize_relation_value(child.stem) == selected_stem
        ):
            _add_related_file(files, seen, root, match, "Same Unity asset name")

    for path_id in path_ids:
        unity_object = objects_by_path_id.get(path_id)
        if not unity_object:
            continue
        if unity_object.get("name"):
            _add_relation_term(terms, unity_object["name"])
        file_path = bundle_root and _find_object_file(bundle_root, unity_object)
        if file_path:
            _add_related_file(files, seen, root, file_path, f"Unity reference · {unity_object.get('type')}")
        else:
            unity_objects.append(
                {
                    "name": unity_object.get("name") or f"{unity_object.get('type')} {path_id}",
                    "assetType": f"Unity {unity_object.get('type')}",
                    "pathId": path_id,
                    "relation": "Unity object reference",
                }
            )
        if len(files) + len(unity_objects) >= MAX_RELATED_RESULTS:
            break

    # wiki_dir is the data directory itself (…/wiki/data), matching config.
    index_rows = _read_id_index(Path(roots.wiki_dir) / "idIndex.json")
    return {
        "path": relative,
        "assets": files[:MAX_RELATED_RESULTS],
        "unityObjects": unity_objects[:MAX_RELATED_RESULTS],
        "tables": _find_related_tables(index_rows, terms, ids),
    }
