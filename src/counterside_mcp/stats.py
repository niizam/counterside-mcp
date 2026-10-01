"""Stat ids, asset typing, and value normalisation.

Ported from Mod:Side: ``statTypeValue`` and ``assetTypeFor``
(``modules/packet-codec/index.js``, ``server/assetViewer.js``).
"""

import json
import re
import unicodedata
from importlib import resources

TEXT_EXTENSIONS = {
    ".atlas",
    ".bytes",
    ".csv",
    ".json",
    ".log",
    ".lua",
    ".md",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
UNITY_RESOURCE_TYPES = {"AudioClip", "Sprite", "TextAsset", "Texture2D"}

_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")


def _load_stat_types() -> dict[str, int]:
    with resources.files("counterside_mcp.data").joinpath("nkm_stat_type.json").open(
        encoding="utf-8"
    ) as handle:
        return json.load(handle)


# Copied verbatim from the Node source by tools/extract_stat_types.cjs.
NKM_STAT_TYPE: dict[str, int] = _load_stat_types()


def stat_type_value(value) -> int:
    """Numeric passthrough, then numeric string, then name lookup, else 0."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value or "").strip()
    if not text:
        return 0
    if text.lstrip("-").isdigit():
        return int(text)
    return NKM_STAT_TYPE.get(text, 0)


def asset_type_for(relative_path: str, extension: str) -> str:
    """Classify an extracted-asset entry the way Mod:Side's tree does."""
    extension = (extension or "").lower()
    if extension == ".png":
        return "Image"
    if extension == ".wav":
        return "Audio"
    if extension == ".skel":
        return "Spine skeleton"
    if extension == ".atlas":
        return "Spine atlas"
    if extension == ".bytes":
        return "TextAsset bytes"
    parts = [part for part in str(relative_path or "").replace("\\", "/").split("/") if part]
    if "TypeTree" in parts:
        index = parts.index("TypeTree")
        if index + 1 < len(parts):
            return f"Unity {parts[index + 1]}"
    for part in parts:
        if part.endswith("Meta") and part[:-4] in UNITY_RESOURCE_TYPES:
            return f"Unity {part[:-4]} metadata"
    for part in parts:
        if part in UNITY_RESOURCE_TYPES:
            return part
    if "ObjectIndex" in parts:
        return "Unity object index"
    return extension[1:].upper() if extension else "File"


def humanize(value) -> str:
    """Turn a stat id into a display label: NST_HP_REGEN_RATE -> 'Hp Regen Rate'."""
    text = str(value or "").replace("NST_", "").replace("_", " ").lower()
    return text.title()


def normalize_relation_value(value) -> str:
    """NFKC, lowercase, then strip everything but letters and digits."""
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    return "".join(ch for ch in text if ch.isalnum())


def tokenize(value) -> list[str]:
    """Split a query into search terms, dropping single characters."""
    return [term for term in _TOKEN_SPLIT.split(str(value or "").lower()) if len(term) > 1]


def normalize_search_token(value) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())
