"""Resolve the four data roots, from environment or a RevivalSide directory."""

import os
from dataclasses import dataclass
from pathlib import Path

from .errors import DomainError
from .paths import normalize_relative_path  # noqa: F401  (re-exported convenience)

# A root whose own name is one of these is already a bundle layout root and is
# used directly rather than having the names appended again.
TABLE_ROOT_NAMES = {"assetbundles", "streamingassets"}


@dataclass(frozen=True)
class Roots:
    revival_root: Path
    asset_dirs: tuple[Path, ...]
    table_dirs: tuple[Path, ...]
    wiki_dir: Path
    server_data_dir: Path


def split_path_list(value: str | None) -> list[str]:
    """Split a comma- or semicolon-delimited path list, dropping blanks."""
    if not value:
        return []
    chunks = str(value).replace(";", ",").split(",")
    return [chunk.strip() for chunk in chunks if chunk.strip()]


def expand_root(root: Path) -> tuple[Path, ...]:
    """A root ending in Assetbundles/StreamingAssets is used directly; else both."""
    root = Path(root)
    if root.name.lower() in TABLE_ROOT_NAMES:
        return (root,)
    return (root / "Assetbundles", root / "StreamingAssets")


def _default_asset_root(revival_root: Path) -> Path:
    all_dir = revival_root / "extracted-assets" / "all"
    return all_dir if all_dir.exists() else revival_root / "extracted-assets"


def _find_revival_root(env, package_dir: Path | None) -> Path:
    configured = (env or {}).get("CS_REVIVALSIDE_ROOT")
    if configured:
        path = Path(configured).expanduser()
        if path.exists():
            return path
        raise DomainError(
            f"CS_REVIVALSIDE_ROOT is set to {configured!r} but that directory does not exist."
        )
    if package_dir is not None:
        # The package lives at <repo>/src/counterside_mcp, so the sibling
        # RevivalSide/ sits next to the repo root, not next to the module.
        # Walk up a bounded number of levels and take the first that has one.
        current = Path(package_dir).resolve()
        for _ in range(4):
            sibling = current.parent / "RevivalSide"
            if sibling.exists():
                return sibling
            if current.parent == current:
                break
            current = current.parent
    raise DomainError(
        "Could not locate a RevivalSide directory. Set CS_REVIVALSIDE_ROOT to your "
        "RevivalSide checkout or install directory, or set CS_ASSET_VIEWER_ROOT and "
        "CS_GAMEPLAY_TABLES_DIR individually."
    )


def resolve_roots(
    env: dict | None = None,
    package_dir: Path | None = None,
    explicit_asset_root: str | None = None,
) -> Roots:
    """Resolve every root, honouring per-root environment overrides."""
    env = env if env is not None else os.environ
    revival_root = _find_revival_root(env, package_dir)

    asset_value = explicit_asset_root or env.get("CS_ASSET_VIEWER_ROOT")
    if asset_value:
        asset_dirs: list[Path] = [Path(asset_value).expanduser()]
    else:
        asset_dirs = [_default_asset_root(revival_root)]

    table_values = (
        split_path_list(env.get("CS_GAMEPLAY_TABLES_DIR"))
        + split_path_list(env.get("CS_GAMEPLAY_JSON_ROOTS"))
        + split_path_list(env.get("CS_GAMEPLAY_TABLE_ROOTS"))
    )
    table_roots = [Path(value).expanduser() for value in table_values] or [
        revival_root / "gameplay-jsons"
    ]
    table_dirs: list[Path] = []
    for root in table_roots:
        for candidate in expand_root(root):
            if candidate not in table_dirs:
                table_dirs.append(candidate)

    wiki_value = env.get("CS_COUNTERSIDE_WIKI")
    wiki_dir = Path(wiki_value).expanduser() if wiki_value else revival_root / "wiki" / "data"
    server_value = env.get("CS_SERVER_DATA_DIR")
    server_data_dir = (
        Path(server_value).expanduser() if server_value else revival_root / "server-data"
    )

    return Roots(
        revival_root=revival_root,
        asset_dirs=tuple(asset_dirs),
        table_dirs=tuple(table_dirs),
        wiki_dir=wiki_dir,
        server_data_dir=server_data_dir,
    )


def _existing(dirs: tuple[Path, ...]) -> Path | None:
    for directory in dirs:
        if directory.exists():
            return directory
    return None


def health(roots: Roots) -> dict:
    """Describe every root. Never raises: a bad root must be visible, not fatal."""
    asset = _existing(roots.asset_dirs)
    table = _existing(roots.table_dirs)
    return {
        "revivalRoot": str(roots.revival_root),
        "roots": {
            "asset": {
                "candidates": [str(p) for p in roots.asset_dirs],
                "resolved": str(asset) if asset else None,
                "exists": asset is not None,
            },
            "table": {
                "candidates": [str(p) for p in roots.table_dirs],
                "resolved": str(table) if table else None,
                "exists": table is not None,
            },
            "wiki": {"resolved": str(roots.wiki_dir), "exists": roots.wiki_dir.exists()},
            "serverData": {
                "resolved": str(roots.server_data_dir),
                "exists": roots.server_data_dir.exists(),
            },
        },
    }
