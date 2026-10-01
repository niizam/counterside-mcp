"""Path normalisation and containment.

Mirrors Mod:Side's ``resolveExistingAssetPath`` / ``isInside`` so an agent
cannot be steered outside the configured asset root.
"""

import re
from pathlib import Path, PurePosixPath

from .errors import DomainError

# A Windows drive prefix ("C:") or any leading slash means the caller passed
# an absolute path; both are rejected rather than reinterpreted.
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")


def normalize_relative_path(value: str) -> str:
    """Backslashes to '/', drop leading slash, collapse '.' and '..'.

    Pure and non-raising: this is used for display paths as well as lookups.
    Callers that guard against escape use :func:`reject_unsafe_relative`
    first, which inspects the raw string before it is collapsed.
    """
    text = str(value or "").replace("\\", "/")
    parts: list[str] = []
    for part in text.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def reject_unsafe_relative(value: str, label: str = "Asset") -> None:
    """Reject absolute paths and '..' segments that climb above the root.

    Checked on the raw string, because collapsing '..' would otherwise turn an
    escape attempt into a benign-looking path that merely fails to exist.
    """
    text = str(value or "").replace("\\", "/")
    if text.startswith("/") or _DRIVE_PREFIX.match(text):
        raise DomainError(f"{label} path resolves outside the asset root: {value}")
    depth = 0
    for part in text.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            depth -= 1
            if depth < 0:
                raise DomainError(f"{label} path resolves outside the asset root: {value}")
        else:
            depth += 1


def is_inside(root: Path, candidate: Path) -> bool:
    """True when ``candidate`` is ``root`` or lives beneath it."""
    try:
        root_real = Path(root).resolve(strict=True)
    except OSError:
        root_real = Path(root).resolve()
    candidate_real = Path(candidate).resolve()
    return candidate_real == root_real or root_real in candidate_real.parents


def resolve_existing(root: Path, relative: str, label: str = "Asset") -> Path:
    """Resolve ``relative`` under ``root``, rejecting escapes and misses."""
    normalized = normalize_relative_path(relative)
    if not normalized:
        raise DomainError(f"{label} path is required.")
    reject_unsafe_relative(relative, label)
    candidate = Path(root, *PurePosixPath(normalized).parts)
    # Defence in depth: containment is re-checked on the resolved path.
    if not is_inside(root, candidate):
        raise DomainError(f"{label} path resolves outside the asset root: {relative}")
    if not candidate.exists():
        raise DomainError(f"{label} was not found: {normalized}", status=404)
    return candidate


def resolve_existing_dir(root: Path, relative: str, label: str = "Asset directory") -> Path:
    path = resolve_existing(root, relative, label)
    if not path.is_dir():
        raise DomainError(f"{label} is not a directory: {relative}")
    return path
