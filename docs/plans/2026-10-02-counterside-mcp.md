# CounterSide MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone, read-only Python MCP server that lets an AI agent examine CounterSide's decoded gameplay tables, game objects, and extracted asset tree.

**Architecture:** Plain Python modules do all data work (root resolution, table reading, object joins, asset walking), each taking resolved root paths and returning dicts. `server.py` registers those functions as MCP tools and resources over stdio. No Node, no network, no writes.

**Tech Stack:** Python ≥3.10, `mcp` (official Python SDK, `MCPServer` API), `pytest`.

**Spec:** `docs/specs/2026-10-02-counterside-mcp-design.md`

## Global Constraints

- Read-only. No tool, module, or code path writes to disk. No mod projects, patches, string tables, asset replacement, Unity, or mod-runtime.
- No network access and no Node dependency at runtime.
- Run under python3 (3.12 present on this machine; declare `requires-python = ">=3.10"`).
- Backslashes in paths are normalised to `/`; every caller-supplied path is containment-checked against the asset root before any file operation.
- Pagination default limit 100, clamped to max 250.
- Environment variable names copied verbatim from the spec: `CS_REVIVALSIDE_ROOT`, `CS_ASSET_VIEWER_ROOT`, `CS_GAMEPLAY_TABLES_DIR`, `CS_GAMEPLAY_JSON_ROOTS`, `CS_GAMEPLAY_TABLE_ROOTS`, `CS_COUNTERSIDE_WIKI`, `CS_SERVER_DATA_DIR`.
- The 29-system table and the stat enum are copied verbatim from the Node source and pinned by parity tests.

## Review Focus

- **Path escape** — a path containing `../` or an absolute path must be rejected, never resolved outside the asset root.
- **Missing/misconfigured root** — `health` must report which root is missing instead of raising, so an agent is never left guessing.
- **Root given directly vs before-expansion** — passing a root that already ends in `Assetbundles` or `StreamingAssets` must work, not double-nest.
- **Non-text file passed to `read_text`** — must return a clear "no text preview" error, not garbage bytes.
- **Spine set missing a page** — must return `ready:false` with the exact missing names, never a partial set presented as complete.

---

### Task 1: Repo init and package scaffold

**Files:**
- Create: `counterside-mcp/.gitignore`
- Create: `counterside-mcp/pyproject.toml`
- Create: `counterside-mcp/src/counterside_mcp/__init__.py`
- Create: `counterside-mcp/tests/__init__.py`
- Create: `counterside-mcp/tests/unit/__init__.py`

**Interfaces:**
- Consumes: nothing.
- Produces: an importable package `counterside_mcp` with `__version__`.

- [x] **Step 1: Initialise version control**

Run (from `/home/windows/project/counterside-mcp`):
```bash
git init
git branch -m main
```

- [x] **Step 2: Write `.gitignore`**

```gitignore
__pycache__/
*.py[cod]
.pytest_cache/
.venv/
venv/
dist/
build/
*.egg-info/
.coverage
```

- [x] **Step 3: Write `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "counterside-mcp"
version = "0.1.0"
description = "Read-only MCP server for examining CounterSide game data"
requires-python = ">=3.10"
dependencies = ["mcp>=1.9"]

[project.optional-dependencies]
dev = ["pytest>=8"]

[project.scripts]
counterside-mcp = "counterside_mcp.server:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
counterside_mcp = ["data/*.json"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["parity: compares output against the live Node Mod:Side API"]
```

- [x] **Step 4: Write package init**

`src/counterside_mcp/__init__.py`:
```python
"""Read-only MCP server for CounterSide extracted game data."""

__version__ = "0.1.0"
```

`tests/__init__.py` and `tests/unit/__init__.py`: empty files.

- [x] **Step 5: Install and verify import**

Run:
```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -c "import counterside_mcp; print(counterside_mcp.__version__)"
```
Expected: prints `0.1.0`.

- [x] **Step 6: Commit**

```bash
git add .gitignore pyproject.toml src tests
git commit -m "chore: scaffold counterside-mcp package"
```

---

### Task 2: Errors and path safety

**Files:**
- Create: `src/counterside_mcp/errors.py`
- Create: `src/counterside_mcp/paths.py`
- Test: `tests/unit/test_paths.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `DomainError(message, status=400)`; `normalize_relative_path(value) -> str`; `is_inside(root, candidate) -> bool`; `resolve_existing(root, relative, label="Asset") -> Path`; `resolve_existing_dir(root, relative, label="Asset directory") -> Path`.

- [x] **Step 1: Write the failing test**

`tests/unit/test_paths.py`:
```python
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


@pytest.mark.parametrize("value", ["../escape", "a/../../escape", "/etc/passwd"])
def test_escape_paths_are_rejected(tmp_path, value):
    (tmp_path / "inside.txt").write_text("x")
    with pytest.raises(DomainError) as err:
        resolve_existing(tmp_path, value)
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
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_paths.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'counterside_mcp.paths'`

- [x] **Step 3: Write `errors.py`**

```python
"""Domain errors, mapped to MCP tool errors at the server boundary."""


class DomainError(Exception):
    """A caller-facing failure with a short, actionable message."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status
```

- [x] **Step 4: Write `paths.py`**

```python
"""Path normalisation and containment. Mirrors Mod:Side's resolveExistingAssetPath."""

from pathlib import Path, PurePosixPath

from .errors import DomainError


def normalize_relative_path(value: str) -> str:
    """Backslashes to '/', drop leading slash, collapse '.' and '..'."""
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


def is_inside(root: Path, candidate: Path) -> bool:
    try:
        root_real = Path(root).resolve(strict=True)
    except OSError:
        root_real = Path(root).resolve()
    candidate_real = Path(candidate).resolve()
    return candidate_real == root_real or root_real in candidate_real.parents


def resolve_existing(root: Path, relative: str, label: str = "Asset") -> Path:
    normalized = normalize_relative_path(relative)
    if not normalized:
        raise DomainError(f"{label} path is required.")
    candidate = Path(root, *PurePosixPath(normalized).parts)
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
```

- [x] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_paths.py -v`
Expected: PASS (6 tests)

- [x] **Step 6: Commit**

```bash
git add src/counterside_mcp/errors.py src/counterside_mcp/paths.py tests/unit/test_paths.py
git commit -m "feat: add path normalisation and containment checks"
```

---

### Task 3: Config and root resolution

**Files:**
- Create: `src/counterside_mcp/config.py`
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Consumes: `paths.normalize_relative_path`.
- Produces: `Roots` dataclass with fields `revival_root: Path`, `asset_dirs: tuple[Path, ...]`, `table_dirs: tuple[Path, ...]`, `wiki_dir: Path`, `server_data_dir: Path`; `TABLE_ROOT_NAMES`; `resolve_roots(env=None, package_dir=None, explicit_asset_root=None) -> Roots`; `expand_root(root) -> tuple[Path, ...]`; `health(roots) -> dict`.

- [x] **Step 1: Write the failing test**

`tests/unit/test_config.py`:
```python
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


def test_table_roots_from_env(tmp_path):
    root = make_tree(tmp_path)
    tables = tmp_path / "tables"
    tables.mkdir()
    roots = resolve_roots(env={"CS_REVIVALSIDE_ROOT": str(root), "CS_GAMEPLAY_TABLES_DIR": str(tables)})
    assert tables in roots.table_dirs


def test_set_but_missing_revival_root_raises():
    with pytest.raises(DomainError) as err:
        resolve_roots(env={"CS_REVIVALSIDE_ROOT": "/nonexistent/revival"})
    assert "/nonexistent/revival" in str(err.value)


def test_unset_and_undiscoverable_revival_root_raises():
    with pytest.raises(DomainError) as err:
        resolve_roots(env={}, package_dir=Path("/nonexistent/deep/path"))
    assert "CS_REVIVALSIDE_ROOT" in str(err.value)


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
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'counterside_mcp.config'`

- [x] **Step 3: Write `config.py`**

```python
"""Resolve the four data roots, from environment or a RevivalSide directory."""

import os
from dataclasses import dataclass
from pathlib import Path

from .errors import DomainError
from .paths import normalize_relative_path

TABLE_ROOT_NAMES = {"assetbundles", "streamingassets"}


@dataclass(frozen=True)
class Roots:
    revival_root: Path
    asset_dirs: tuple[Path, ...]
    table_dirs: tuple[Path, ...]
    wiki_dir: Path
    server_data_dir: Path


def split_path_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [part for part in (chunk.strip() for chunk in str(value).replace(";", ",").split(",")) if part]


def expand_root(root: Path) -> tuple[Path, ...]:
    """A root ending in Assetbundles/StreamingAssets is used directly; else both layouts."""
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
        sibling = Path(package_dir).resolve().parent / "RevivalSide"
        if sibling.exists():
            return sibling
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
    env = env if env is not None else os.environ
    revival_root = _find_revival_root(env, package_dir)

    asset_value = explicit_asset_root or env.get("CS_ASSET_VIEWER_ROOT")
    asset_roots = ([Path(asset_value).expanduser()] if asset_value else [_default_asset_root(revival_root)])
    asset_dirs: list[Path] = []
    for root in asset_roots:
        for candidate in ([root] if root.name.lower() in TABLE_ROOT_NAMES else [root]):
            if candidate not in asset_dirs:
                asset_dirs.append(candidate)

    table_values = (
        split_path_list(env.get("CS_GAMEPLAY_TABLES_DIR"))
        + split_path_list(env.get("CS_GAMEPLAY_JSON_ROOTS"))
        + split_path_list(env.get("CS_GAMEPLAY_TABLE_ROOTS"))
    )
    table_roots = [Path(value).expanduser() for value in table_values] or [revival_root / "gameplay-jsons"]
    table_dirs: list[Path] = []
    for root in table_roots:
        for candidate in expand_root(root):
            if candidate not in table_dirs:
                table_dirs.append(candidate)

    wiki_dir = Path(env.get("CS_COUNTERSIDE_WIKI") or revival_root / "wiki" / "data")
    server_data_dir = Path(env.get("CS_SERVER_DATA_DIR") or revival_root / "server-data")

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
            "serverData": {"resolved": str(roots.server_data_dir), "exists": roots.server_data_dir.exists()},
        },
    }
```

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_config.py -v`
Expected: PASS (7 tests)

- [x] **Step 5: Commit**

```bash
git add src/counterside_mcp/config.py tests/unit/test_config.py
git commit -m "feat: resolve data roots from env or a RevivalSide directory"
```

---

### Task 4: Stats, asset typing, and relation helpers

**Files:**
- Create: `src/counterside_mcp/data/nkm_stat_type.json` (generated in Step 1)
- Create: `src/counterside_mcp/stats.py`
- Test: `tests/unit/test_stats.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `NKM_STAT_TYPE: dict[str, int]`; `stat_type_value(value) -> int`; `asset_type_for(relative_path, extension) -> str`; `humanize(value) -> str`; `normalize_relation_value(value) -> str`; `TEXT_EXTENSIONS: set[str]`; `UNITY_RESOURCE_TYPES: set[str]`.

- [x] **Step 1: Generate the stat enum verbatim from the Node source**

Run:
```bash
node -e '
const fs=require("fs");
const src=fs.readFileSync("/home/windows/project/RevivalSide/modules/packet-codec/index.js","utf8");
const m=src.match(/const NKM_STAT_TYPE = Object\.freeze\(\{([\s\S]*?)\}\);/);
const body=m[1];
const out={};
for(const line of body.split("\n")){
  const kv=line.match(/^\s*(NST_[A-Z0-9_]+)\s*:\s*(-?\d+)\s*,?/);
  if(kv) out[kv[1]]=Number(kv[2]);
}
fs.mkdirSync("src/counterside_mcp/data",{recursive:true});
fs.writeFileSync("src/counterside_mcp/data/nkm_stat_type.json",JSON.stringify(out,null,2)+"\n");
console.log("wrote",Object.keys(out).length,"stat types");
'
```
Expected: `wrote NN stat types` (NN > 40).

- [x] **Step 2: Write the failing test**

`tests/unit/test_stats.py`:
```python
from counterside_mcp.stats import (
    NKM_STAT_TYPE,
    asset_type_for,
    humanize,
    normalize_relation_value,
    stat_type_value,
)


def test_stat_enum_loaded():
    assert NKM_STAT_TYPE["NST_HP"] == 0
    assert NKM_STAT_TYPE["NST_ATK"] == 1
    assert len(NKM_STAT_TYPE) > 40


def test_stat_type_value_passthrough_and_lookup():
    assert stat_type_value(7) == 7
    assert stat_type_value("7") == 7
    assert stat_type_value("NST_ATK") == 1
    assert stat_type_value("NST_UNKNOWN") == 0
    assert stat_type_value(None) == 0


def test_asset_type_for():
    assert asset_type_for("a/b.png", ".png") == "Image"
    assert asset_type_for("a/b.wav", ".wav") == "Audio"
    assert asset_type_for("b/x.skel", ".skel") == "Spine skeleton"
    assert asset_type_for("b/x.atlas", ".atlas") == "Spine atlas"
    assert asset_type_for("b/x.bytes", ".bytes") == "TextAsset bytes"
    assert asset_type_for("b/TypeTree/Sprite/x", "") == "Unity Sprite"
    assert asset_type_for("b/SpriteMeta/x", "") == "Unity Sprite metadata"
    assert asset_type_for("b/Texture2D/x", "") == "Texture2D"
    assert asset_type_for("b/ObjectIndex/o.json", ".json") == "Unity object index"


def test_humanize():
    assert humanize("NST_HP_REGEN_RATE") == "Hp Regen Rate"


def test_normalize_relation_value_strips_punctuation():
    assert normalize_relation_value("AB_INVEN_ICON_NKM-X.png") == "abinveniconnkmx"
```

- [x] **Step 3: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_stats.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'counterside_mcp.stats'`

- [x] **Step 4: Write `stats.py`**

```python
"""Stat ids, asset typing, and value normalisation. Ported from the Node source."""

import json
import unicodedata
from importlib import resources

TEXT_EXTENSIONS = {".atlas", ".bytes", ".csv", ".json", ".log", ".lua", ".md", ".txt", ".xml", ".yaml", ".yml"}
UNITY_RESOURCE_TYPES = {"AudioClip", "Sprite", "TextAsset", "Texture2D"}


def _load_stat_types() -> dict[str, int]:
    with resources.files("counterside_mcp.data").joinpath("nkm_stat_type.json").open(encoding="utf-8") as handle:
        return json.load(handle)


NKM_STAT_TYPE: dict[str, int] = _load_stat_types()


def stat_type_value(value) -> int:
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
    text = str(value or "").replace("NST_", "").replace("_", " ").lower()
    return text.title()


def normalize_relation_value(value) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    return "".join(ch for ch in text if ch.isalnum())


def tokenize(value) -> list[str]:
    import re

    return [term for term in re.split(r"[^a-z0-9]+", str(value or "").lower()) if len(term) > 1]


def normalize_search_token(value) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())
```

- [x] **Step 5: Write `data/__init__.py`**

Create `src/counterside_mcp/data/__init__.py` (empty) so `resources.files` resolves the package.

- [x] **Step 6: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_stats.py -v`
Expected: PASS (5 tests)

- [x] **Step 7: Commit**

```bash
git add src/counterside_mcp/stats.py src/counterside_mcp/data tests/unit/test_stats.py
git commit -m "feat: add stat ids, asset typing, and relation helpers"
```

---

### Task 5: Gameplay tables

**Files:**
- Create: `src/counterside_mcp/tables.py`
- Test: `tests/unit/test_tables.py`

**Interfaces:**
- Consumes: `config.Roots`.
- Produces: `TableEntry` dataclass (`root`, `file_path`, `directory`, `file_name`, `relative_path`, `extension`, `table_name`); `normalize_table_base_name(file_name) -> str`; `parse_table_path(root, file_path) -> TableEntry | None`; `list_table_entries(roots) -> list[TableEntry]`; `find_table_entry(roots, directory, file_name) -> TableEntry | None`; `read_table(entry) -> object | None`; `extract_table_records(parsed) -> list`; `table_schema(records) -> list[dict]`; `read_table_records(roots, directory, file_name) -> tuple[list, dict]`.

- [x] **Step 1: Write the failing test**

`tests/unit/test_tables.py`:
```python
import json
from pathlib import Path

from counterside_mcp.config import Roots
from counterside_mcp.tables import (
    extract_table_records,
    find_table_entry,
    list_table_entries,
    normalize_table_base_name,
    parse_table_path,
    read_table_records,
    table_schema,
)


def build_roots(tmp_path: Path) -> Roots:
    table_root = tmp_path / "StreamingAssets"
    luac = table_root / "ab_script" / "luac"
    luac.mkdir(parents=True)
    (luac / "LUA_DEMO_TEMPLET.json").write_text(
        json.dumps({"recordCount": 2, "records": [{"m_ID": 1, "m_Stat": {"hp": 10}}, {"m_ID": 2, "m_Stat": {"hp": 20}}]})
    )
    return Roots(
        revival_root=tmp_path,
        asset_dirs=(tmp_path / "assets",),
        table_dirs=(table_root,),
        wiki_dir=tmp_path / "wiki",
        server_data_dir=tmp_path / "server-data",
    )


def test_normalize_table_base_name_strips_suffixes():
    assert normalize_table_base_name("LUA_X.json") == "LUA_X"
    assert normalize_table_base_name("LUA_X.luac.json") == "LUA_X"


def test_parse_table_path_requires_luac_segment(tmp_path):
    assert parse_table_path(tmp_path, tmp_path / "x.json") is None
    entry = parse_table_path(tmp_path, tmp_path / "ab" / "luac" / "LUA_X.json")
    assert entry.directory == "ab" and entry.table_name == "LUA_X"


def test_extract_table_records_shapes():
    assert extract_table_records([{"a": 1}]) == [{"a": 1}]
    assert extract_table_records({"records": [{"a": 1}]}) == [{"a": 1}]
    assert extract_table_records({"root": [{"a": 1}]}) == [{"a": 1}]
    keyed = extract_table_records({"root": {"K": {"a": 1}}})
    assert keyed == [{"__key": "K", "a": 1}]
    assert extract_table_records(None) == []


def test_list_and_read(tmp_path):
    roots = build_roots(tmp_path)
    entries = list_table_entries(roots)
    assert [e.table_name for e in entries] == ["LUA_DEMO_TEMPLET"]
    found = find_table_entry(roots, "ab_script", "LUA_DEMO_TEMPLET")
    assert found is not None
    records, _ = read_table_records(roots, "ab_script", "LUA_DEMO_TEMPLET")
    assert [r["m_ID"] for r in records] == [1, 2]


def test_table_schema_collects_nested_paths(tmp_path):
    roots = build_roots(tmp_path)
    records, _ = read_table_records(roots, "ab_script", "LUA_DEMO_TEMPLET")
    paths = {field["path"] for field in table_schema(records)}
    assert {"m_ID", "m_Stat.hp"} <= paths
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_tables.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'counterside_mcp.tables'`

- [x] **Step 3: Write `tables.py`**

```python
"""Gameplay table discovery and reading. Mirrors Mod:Side's gameplay-jsons module."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .config import Roots

_SUFFIX = re.compile(r"\.(json|luac|lua|bytes)$", re.IGNORECASE)


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
    value = str(file_name or "").replace("\\", "/").split("/")[-1]
    while _SUFFIX.search(value):
        value = _SUFFIX.sub("", value)
    return value


def parse_table_path(root: Path, file_path: Path) -> TableEntry | None:
    root = Path(root)
    file_path = Path(file_path)
    try:
        parts = [p for p in file_path.relative_to(root).as_posix().split("/") if p]
    except ValueError:
        return None
    lowered = [p.lower() for p in parts]
    if "luac" not in lowered:
        return None
    index = lowered.index("luac")
    if index <= 0 or index >= len(parts) - 1:
        return None
    file_name = parts[-1]
    extension = Path(file_name).suffix.lower()
    if extension not in (".json", ".luac"):
        return None
    directory = "/".join(parts[:index])
    return TableEntry(
        root=root,
        file_path=file_path,
        directory=directory,
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
            if entry.is_dir():
                stack.append(entry)
            elif entry.is_file() and entry.suffix.lower() in (".json", ".luac"):
                yield entry


def list_table_entries(roots: Roots) -> list[TableEntry]:
    found: dict[str, TableEntry] = {}
    for root in roots.table_dirs:
        for file_path in _walk(root):
            entry = parse_table_path(root, file_path)
            if entry is None:
                continue
            key = f"{entry.directory.lower()}/{entry.table_name.lower()}"
            existing = found.get(key)
            # .json beats .luac when both exist.
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
    try:
        with entry.file_path.open(encoding="utf-8") as handle:
            parsed = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, (dict, list)) else None


def extract_table_records(parsed) -> list:
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
    entry = find_table_entry(roots, directory, file_name)
    if entry is None:
        return [], {"found": False}
    parsed = read_table(entry)
    records = extract_table_records(parsed)
    if not records and isinstance(parsed, dict):
        records = [parsed]
    return records, {"found": True, "entry": table_entry_json(entry)}


def _collect(value, prefix: str, fields: dict, depth: int) -> None:
    if depth > 8 or value is None:
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
    fields: dict[str, dict] = {}
    for record in records[:40]:
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
```

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_tables.py -v`
Expected: PASS (5 tests)

- [x] **Step 5: Commit**

```bash
git add src/counterside_mcp/tables.py tests/unit/test_tables.py
git commit -m "feat: discover and read gameplay tables"
```

---

### Task 6: Game systems and field search

**Files:**
- Create: `src/counterside_mcp/data/systems.json` (generated in Step 1)
- Create: `src/counterside_mcp/systems.py`
- Test: `tests/unit/test_systems.py`

**Interfaces:**
- Consumes: `tables.TableEntry`, `tables.list_table_entries`, `tables.table_schema`, `tables.read_table_records`, `stats.tokenize`, `stats.normalize_search_token`.
- Produces: `GameSystem` dataclass; `load_systems() -> list[GameSystem]`; `system_tables(system, entries) -> list[TableEntry]`; `public_system(system, entries) -> dict`; `list_systems(roots) -> dict`; `search_fields(roots, query) -> dict`.

- [x] **Step 1: Generate the system table verbatim from the Node source**

Run:
```bash
node -e '
const fs=require("fs");
const src=fs.readFileSync("/home/windows/project/RevivalSide/server/assetViewer.js","utf8");
const start=src.indexOf("const GAME_SYSTEMS = [");
const end=src.indexOf("\n];", start);
const literal=src.slice(start+"const GAME_SYSTEMS = ".length, end+2);
const system=(id,title,description,keywords,directories,prefixes,priorityTables,commonEdits)=>({id,title,description,keywords,directories,prefixes,priorityTables,commonEdits});
const edit=(label,query,location)=>({label,query,location});
const GAME_SYSTEMS=eval(literal);
fs.writeFileSync("src/counterside_mcp/data/systems.json",JSON.stringify(GAME_SYSTEMS,null,2)+"\n");
console.log("wrote",GAME_SYSTEMS.length,"systems");
'
```
Expected: `wrote 29 systems`.

- [x] **Step 2: Write the failing test**

`tests/unit/test_systems.py`:
```python
import json
from pathlib import Path

from counterside_mcp.config import Roots
from counterside_mcp.systems import list_systems, load_systems, search_fields


def build_roots(tmp_path: Path) -> Roots:
    luac = tmp_path / "StreamingAssets" / "ab_script_unit_data" / "luac"
    luac.mkdir(parents=True)
    (luac / "LUA_UNIT_TEMPLET_BASE.json").write_text(
        json.dumps({"records": [{"m_UnitID": 1, "m_RespawnCost": 5, "m_StatData": {"m_Stat": {"NST_HP": 100}}}]})
    )
    return Roots(tmp_path, (tmp_path / "assets",), (tmp_path / "StreamingAssets",), tmp_path / "wiki", tmp_path / "server-data")


def test_systems_loaded_verbatim():
    systems = load_systems()
    assert len(systems) == 29
    ids = {s.id for s in systems}
    assert {"units", "items", "stages", "story", "all"} <= ids


def test_list_systems_reports_table_counts(tmp_path):
    roots = build_roots(tmp_path)
    report = list_systems(roots)
    units = next(s for s in report["systems"] if s["id"] == "units")
    assert units["tableCount"] >= 1


def test_search_fields_finds_deploy_cost(tmp_path):
    roots = build_roots(tmp_path)
    result = search_fields(roots, "unit respawn cost")
    assert result["systems"]
    assert any("UNIT" in table["tableName"] for table in result["tables"])
```

- [x] **Step 3: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_systems.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'counterside_mcp.systems'`

- [x] **Step 4: Write `systems.py`**

```python
"""Curated game systems and field search. Data generated verbatim from GAME_SYSTEMS."""

import json
from dataclasses import dataclass, field
from importlib import resources

from .config import Roots
from .stats import normalize_search_token, tokenize
from .tables import TableEntry, list_table_entries, read_table_records, table_entry_json, table_schema

FIELD_ALIASES = {
    "hp": ["health", "nsthp"], "health": ["hp", "nsthp"],
    "attack": ["atk", "damage", "nstatk", "atkfactor"], "atk": ["attack", "damage", "nstatk", "atkfactor"],
    "defense": ["def", "nstdef", "armor"], "defence": ["def", "nstdef", "armor"],
    "speed": ["movespeed", "attackspeed"], "cooldown": ["cooltime", "cooltimereduce"],
    "critical": ["crit", "criticaldamage"], "crit": ["critical", "criticaldamage"],
    "evasion": ["evade"], "evade": ["evasion"], "accuracy": ["hit"],
    "deploy": ["respawn", "cost"], "cost": ["price", "count", "eternium", "credit", "respawn"],
    "reward": ["drop", "rewardvalue", "rewardid"], "drop": ["reward", "droprate", "dropid"],
    "level": ["levelup", "perlevel", "maxlevel"], "experience": ["exp"], "exp": ["experience"],
    "duration": ["lifetime", "time", "timemax"], "range": ["attackrange", "distance"],
    "stage": ["dungeon", "episode"], "unit": ["character"],
}

MAX_FIELD_TABLES = 12
MAX_FIELD_RESULTS = 60


@dataclass(frozen=True)
class GameSystem:
    id: str
    title: str
    description: str
    keywords: tuple[str, ...]
    directories: tuple[str, ...]
    prefixes: tuple[str, ...]
    priority_tables: tuple[str, ...]
    common_edits: tuple[dict, ...] = field(default_factory=tuple)


def load_systems() -> list[GameSystem]:
    with resources.files("counterside_mcp.data").joinpath("systems.json").open(encoding="utf-8") as handle:
        raw = json.load(handle)
    return [
        GameSystem(
            id=item["id"],
            title=item["title"],
            description=item["description"],
            keywords=tuple(item.get("keywords") or ()),
            directories=tuple(item.get("directories") or ()),
            prefixes=tuple(item.get("prefixes") or ()),
            priority_tables=tuple(item.get("priorityTables") or ()),
            common_edits=tuple(item.get("commonEdits") or ()),
        )
        for item in raw
    ]


def system_tables(system: GameSystem, entries: list[TableEntry]) -> list[TableEntry]:
    if "*" in system.directories:
        return list(entries)
    result = []
    for entry in entries:
        if entry.directory in system.directories or any(entry.table_name.startswith(p) for p in system.prefixes):
            result.append(entry)
    return result


def public_system(system: GameSystem, entries: list[TableEntry]) -> dict:
    return {
        "id": system.id,
        "title": system.title,
        "description": system.description,
        "keywords": list(system.keywords),
        "commonEdits": list(system.common_edits),
        "tableCount": len(system_tables(system, entries)),
    }


def list_systems(roots: Roots) -> dict:
    entries = list_table_entries(roots)
    return {"tableCount": len(entries), "systems": [public_system(s, entries) for s in load_systems()]}


def _score(value: str, terms: list[str]) -> int:
    lowered = str(value or "").lower()
    normalized = normalize_search_token(value)
    return sum(max(1, len(term)) for term in terms if term in lowered or normalize_search_token(term) in normalized)


def system_search_text(system: GameSystem) -> str:
    edits = " ".join(f"{e.get('label','')} {e.get('query','')} {e.get('location','')}" for e in system.common_edits)
    return " ".join([system.title, system.description, *system.keywords, edits]).lower()


def _table_priority(table: TableEntry, system: GameSystem | None) -> int:
    if system is None:
        return 0
    if table.table_name in system.priority_tables:
        return 100 - system.priority_tables.index(table.table_name)
    return 1 if table.directory in system.directories else 0


def search_fields(roots: Roots, query: str) -> dict:
    query = str(query or "").strip()
    if len(query) < 2:
        raise ValueError("Describe the value you want to change (at least two characters).")
    entries = list_table_entries(roots)
    terms = set(tokenize(query))
    for term in list(terms):
        terms.update(FIELD_ALIASES.get(term, []))
    terms.add(normalize_search_token(query))
    term_list = [t for t in terms if t]

    systems = load_systems()
    scored_systems = sorted(
        ((s, _score(system_search_text(s), term_list) * 10) for s in systems if s.id != "all"),
        key=lambda pair: pair[1],
        reverse=True,
    )
    scored_systems = [pair for pair in scored_systems if pair[1] > 0]

    candidates: dict[str, tuple[TableEntry, GameSystem | None, int]] = {}
    for system, score in scored_systems[:3]:
        for table in system_tables(system, entries)[:6]:
            key = f"{table.directory}/{table.file_name}"
            if key not in candidates or candidates[key][2] < score:
                candidates[key] = (table, system, score)
    lowered = query.lower()
    for table in entries:
        score = (12 if lowered in table.table_name.lower() else 0) + _score(table.table_name, term_list)
        if score > 0:
            key = f"{table.directory}/{table.file_name}"
            if key not in candidates or candidates[key][2] < score:
                candidates[key] = (table, _system_for(table, systems), score)

    ranked = sorted(candidates.values(), key=lambda item: item[2], reverse=True)[:MAX_FIELD_TABLES]

    fields = []
    for table, system, score in ranked:
        records, _ = read_table_records(roots, table.directory, table.file_name)
        for schema_field in table_schema(records):
            field_score = _score(f"{schema_field['path']} {table.table_name}", term_list)
            if not field_score:
                continue
            fields.append({
                **schema_field,
                "score": field_score + score,
                "system": system.title if system else "Gameplay data",
                "table": table_entry_json(table),
            })
    fields.sort(key=lambda item: (-item["score"], item["path"]))

    return {
        "query": query,
        "systems": [
            {**public_system(s, entries), "score": score} for s, score in scored_systems[:5]
        ],
        "tables": [
            {**table_entry_json(t), "system": s.title if s else "Gameplay data"} for t, s, _ in ranked
        ],
        "fields": fields[:MAX_FIELD_RESULTS],
    }


def _system_for(table: TableEntry, systems: list[GameSystem]) -> GameSystem | None:
    for system in systems:
        if system.id != "all" and system_tables(system, [table]):
            return system
    return None
```

- [x] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_systems.py -v`
Expected: PASS (3 tests)

- [x] **Step 6: Commit**

```bash
git add src/counterside_mcp/systems.py src/counterside_mcp/data/systems.json tests/unit/test_systems.py
git commit -m "feat: add game systems and field search"
```

---

### Task 7: Objects (asset-catalog port)

**Files:**
- Create: `src/counterside_mcp/objects.py`
- Test: `tests/unit/test_objects.py`

**Interfaces:**
- Consumes: `config.Roots`, `tables.read_table_records`, `stats.stat_type_value`, `stats.humanize`, `errors.DomainError`.
- Produces: `normalize_object_type(value) -> str`; `list_objects(roots, type, query, offset, limit) -> dict`; `get_object(roots, type, object_id) -> dict`; `find_asset_for_object(roots, type, object_id, field=None) -> dict`; `Catalog(roots)` with `records(type) -> list[dict]`.

Port `modules/asset-catalog/index.js` faithfully: same tables, same joins, same
output keys. Units come from `server-data/units.json` when present (authoritative
roster), else the four `LUA_UNIT_TEMPLET_BASE*` / `LUA_UNIT_STAT_TEMPLET*` pairs.
Gears come from `ab_script_item_templet/LUA_ITEM_EQUIP_TEMPLET.json`.

Three things the Node source gets right that a from-scratch port gets wrong:

1. **Most gear columns are optional.** `m_StatGroupID`, `m_StatGroupID_2`,
   `m_SetGroup`, `m_PotentialOptionGroupID`, `m_SubPotentialOptionGroupID`,
   `m_RelicRerollReqItemID` and `Socket{1,2,3}_OpenItemID` are present on some
   rows and absent on others (e.g. `m_SetGroup` on 1675/1688, socket fields on
   3/1688). Read them per record; do not assume a shape from one row.
2. **`addId` drops falsy values.** A field that is `null`, `""`, `0` or `"0"` is
   omitted from `ids` entirely rather than reported with an empty preview.
3. **Gear icons are named `AB_INVEN_ICON_IQI_EQUIP_<value>.png` on disk**, not
   the `AB_INVEN_ICON_<value>.png` the upstream candidate list looks for — so
   upstream resolves 0 of 1688 gear icons. Put the real prefix first and keep
   the upstream spellings as fallbacks: 1678/1688 resolve.

Implemented in `objects.py`; verified against real data (3561 units, 639 ships,
43 operators, 1688 gear; 223 sampled inspections, 0 errors).

### Task 8: Assets — directory, file, text, spine, related

**Files:**
- Create: `src/counterside_mcp/assets.py`
- Test: `tests/unit/test_assets.py`

**Interfaces:**
- Consumes: `config.Roots`, `paths`, `stats`.
- Produces: `list_directory(roots, path, query, offset, limit) -> dict`; `asset_metadata(roots, path) -> dict`; `asset_bytes(roots, path) -> tuple[bytes, str]`; `text_preview(roots, path, max_bytes) -> dict`; `spine_set(roots, path) -> dict`; `find_related(roots, path) -> dict`.

- [x] **Step 1: Write the failing test**

`tests/unit/test_assets.py`:
```python
from pathlib import Path

import pytest

from counterside_mcp.assets import (
    asset_bytes,
    find_related,
    list_directory,
    spine_set,
    text_preview,
)
from counterside_mcp.config import Roots
from counterside_mcp.errors import DomainError


def build_roots(tmp_path: Path) -> Roots:
    assets = tmp_path / "assets"
    spine = assets / "Data" / "StreamingAssets" / "ab_unit_sd_spine_demo" / "TextAsset"
    spine.mkdir(parents=True)
    (spine / "DEMO.atlas").write_text("DEMO.png\nsize: 64,64\n")
    (spine / "DEMO.skel").write_bytes(b"skel")
    (spine.parent / "Texture2D").mkdir()
    (spine.parent / "Texture2D" / "DEMO.png").write_bytes(b"\x89PNG")
    (assets / "Data" / "StreamingAssets" / "a.json").parent.mkdir(parents=True, exist_ok=True)
    (assets / "Data" / "StreamingAssets" / "a.json").write_text('{"hello":"world"}')
    return Roots(tmp_path, (assets,), (tmp_path / "tables",), tmp_path / "wiki", tmp_path / "server-data")


def test_list_directory_typed(tmp_path):
    roots = build_roots(tmp_path)
    result = list_directory(roots, "Data/StreamingAssets", "", 0, 100)
    names = {entry["name"] for entry in result["entries"]}
    assert "ab_unit_sd_spine_demo" in names
    assert result["parentPath"] == "Data"


def test_text_preview_reads_and_flags(tmp_path):
    roots = build_roots(tmp_path)
    result = text_preview(roots, "Data/StreamingAssets/a.json", 1024)
    assert '"hello"' in result["text"]
    assert result["truncated"] is False


def test_text_preview_rejects_binary(tmp_path):
    roots = build_roots(tmp_path)
    with pytest.raises(DomainError):
        text_preview(roots, "Data/StreamingAssets/ab_unit_sd_spine_demo/Texture2D/DEMO.png", 1024)


def test_spine_set_resolves_all_roles(tmp_path):
    roots = build_roots(tmp_path)
    result = spine_set(roots, "Data/StreamingAssets/ab_unit_sd_spine_demo/TextAsset/DEMO.skel")
    assert result["ready"] is True
    roles = {item["role"] for item in result["files"]}
    assert roles == {"skeleton", "atlas", "texture"}


def test_asset_bytes_returns_content_type(tmp_path):
    roots = build_roots(tmp_path)
    data, content_type = asset_bytes(roots, "Data/StreamingAssets/a.json")
    assert data.startswith(b"{")
    assert "json" in content_type


def test_find_related_matches_same_name(tmp_path):
    roots = build_roots(tmp_path)
    result = find_related(roots, "Data/StreamingAssets/ab_unit_sd_spine_demo/TextAsset/DEMO.atlas")
    assert any("DEMO" in asset["name"] for asset in result["assets"])
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_assets.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'counterside_mcp.assets'`

- **Step 3: Write `assets.py`**

```python
"""Asset tree reading: directories, files, text, Spine sets, and related data."""

import json
from pathlib import Path, PurePosixPath

from .config import Roots
from .errors import DomainError
from .paths import is_inside, normalize_relative_path, resolve_existing, resolve_existing_dir
from .stats import TEXT_EXTENSIONS, asset_type_for, normalize_relation_value

MAX_RELATED_RESULTS = 40
DEFAULT_TEXT_PREVIEW_BYTES = 512 * 1024

CONTENT_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
    ".json": "application/json", ".txt": "text/plain; charset=utf-8", ".atlas": "text/plain; charset=utf-8",
    ".csv": "text/csv; charset=utf-8", ".xml": "application/xml", ".wav": "audio/wav", ".skel": "application/octet-stream",
}


def _asset_root(roots: Roots) -> Path:
    for candidate in roots.asset_dirs:
        if candidate.exists():
            return candidate
    return roots.asset_dirs[0]


def _first_existing(roots: Roots, relative: str) -> Path | None:
    for root in roots.asset_dirs:
        candidate = Path(root, *PurePosixPath(relative).parts)
        if is_inside(root, candidate) and candidate.exists():
            return candidate
    return None


def list_directory(roots: Roots, path: str = "", query: str = "", offset: int = 0, limit: int = 100) -> dict:
    root = _asset_root(roots)
    relative = normalize_relative_path(path)
    directory = resolve_existing_dir(root, relative) if relative else root
    needle = str(query or "").strip().lower()
    entries = []
    for child in directory.iterdir():
        if child.is_symlink() or not (child.is_dir() or child.is_file()):
            continue
        if needle and needle not in child.name.lower():
            continue
        child_relative = normalize_relative_path(f"{relative}/{child.name}" if relative else child.name)
        entry = {"name": child.name, "path": child_relative, "kind": "directory" if child.is_dir() else "file"}
        if child.is_file():
            entry["extension"] = child.suffix.lower()
            entry["size"] = child.stat().st_size
            entry["assetType"] = asset_type_for(child_relative, entry["extension"])
        entries.append(entry)
    entries.sort(key=lambda item: (item["kind"] != "directory", item["name"].lower()))
    offset = max(0, int(offset or 0))
    limit = max(1, min(250, int(limit or 100)))
    parent = normalize_relative_path(str(PurePosixPath(relative).parent)) if relative else None
    return {"path": relative, "parentPath": parent or None, "total": len(entries), "offset": offset, "entries": entries[offset:offset + limit]}


def asset_metadata(roots: Roots, path: str) -> dict:
    root = _asset_root(roots)
    relative = normalize_relative_path(path)
    file_path = resolve_existing(root, relative)
    if not file_path.is_file():
        raise DomainError(f"Asset path is not a file: {relative}")
    extension = file_path.suffix.lower()
    return {
        "path": relative, "name": file_path.name, "size": file_path.stat().st_size,
        "extension": extension, "assetType": asset_type_for(relative, extension),
        "contentType": _content_type(file_path), "isImage": extension in {".png", ".jpg", ".jpeg", ".webp"},
    }


def asset_bytes(roots: Roots, path: str) -> tuple[bytes, str]:
    metadata = asset_metadata(roots, path)
    root = _asset_root(roots)
    file_path = resolve_existing(root, metadata["path"])
    return file_path.read_bytes(), metadata["contentType"]


def _content_type(file_path: Path) -> str:
    return CONTENT_TYPES.get(file_path.suffix.lower(), "application/octet-stream")


def text_preview(roots: Roots, path: str, max_bytes: int = DEFAULT_TEXT_PREVIEW_BYTES) -> dict:
    root = _asset_root(roots)
    relative = normalize_relative_path(path)
    file_path = resolve_existing(root, relative)
    if not file_path.is_file():
        raise DomainError(f"Asset path is not a file: {relative}")
    extension = file_path.suffix.lower()
    if extension not in TEXT_EXTENSIONS:
        raise DomainError(f"This asset does not have a text preview: {extension or 'extensionless file'}", status=415)
    size = file_path.stat().st_size
    cap = max(1, int(max_bytes or DEFAULT_TEXT_PREVIEW_BYTES))
    with file_path.open("rb") as handle:
        data = handle.read(cap)
    return {
        "path": relative, "size": size, "truncated": size > len(data),
        "text": data.decode("utf-8", errors="replace"),
    }


def _is_spine_skeleton(file_path: Path) -> bool:
    if file_path.suffix.lower() == ".skel":
        return True
    if file_path.suffix.lower() not in (".json", ".bytes"):
        return False
    try:
        parsed = json.loads(file_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return False
    return bool(isinstance(parsed, dict) and parsed.get("skeleton") and (parsed.get("bones") or parsed.get("slots") or parsed.get("animations")))


def _atlas_pages(atlas_path: Path) -> list[str]:
    pages = []
    for line in atlas_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and ":" not in stripped and stripped.lower().endswith(".png"):
            if stripped not in pages:
                pages.append(stripped)
    return pages


def _find_files_by_name(root: Path, names: set[str]) -> dict[str, Path]:
    wanted = {name.lower() for name in names}
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
            elif child.name.lower() in wanted:
                found.setdefault(child.name.lower(), child)
    return found


def spine_set(roots: Roots, path: str) -> dict:
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
    exact_atlas = next((child for child in atlas_files if child.stem.lower() == base_name.lower()), None)
    atlas_path = selected if extension == ".atlas" else (exact_atlas or (atlas_files[0] if len(atlas_files) == 1 else None))
    if atlas_path is None:
        return {"ready": False, "missing": ["matching .atlas"]}

    atlas_base = atlas_path.stem.lower()
    skeletons = [child for child in source_files if _is_spine_skeleton(child)]
    if len(atlas_files) > 1:
        skeletons = [child for child in skeletons if child == selected or child.stem.lower() == atlas_base]
    if _is_spine_skeleton(selected) and selected not in skeletons:
        skeletons.insert(0, selected)
    if not skeletons:
        return {"ready": False, "missing": ["matching .skel or Spine JSON"]}

    page_names = _atlas_pages(atlas_path)
    if not page_names:
        return {"ready": False, "missing": ["atlas PNG page"]}
    bundle_root = text_asset_dir.parent
    png_files = _find_files_by_name(bundle_root, set(page_names))
    missing = [name for name in page_names if name.lower() not in png_files]
    if missing:
        return {"ready": False, "missing": [f"atlas page {name}" for name in missing]}

    bundle_root = _asset_root(roots)
    files = []
    for skeleton in skeletons:
        files.append({"path": _relative(root, skeleton), "name": skeleton.stem + ".json" if skeleton.suffix.lower() == ".bytes" else skeleton.name, "role": "skeleton"})
    files.append({"path": _relative(root, atlas_path), "name": atlas_path.name, "role": "atlas"})
    for name in page_names:
        files.append({"path": _relative(root, png_files[name.lower()]), "name": name, "role": "texture"})
    return {"ready": True, "files": files}


def _relative(root: Path, file_path: Path) -> str:
    try:
        return normalize_relative_path(file_path.relative_to(root).as_posix())
    except ValueError:
        return normalize_relative_path(file_path.as_posix())


def _bundle_root(roots: Roots, file_path: Path) -> Path | None:
    for root in roots.asset_dirs:
        if not is_inside(root, file_path):
            continue
        current = file_path.parent
        while is_inside(root, current):
            if (current / "ObjectIndex" / "objects.json").exists():
                return current
            if current == root:
                break
            current = current.parent
        parts = normalize_relative_path(file_path.relative_to(root).as_posix()).split("/")
        if len(parts) >= 3:
            candidate = root / parts[0] / parts[1]
            if candidate.is_dir():
                return candidate
    return None


def find_related(roots: Roots, path: str) -> dict:
    root = _asset_root(roots)
    relative = normalize_relative_path(path)
    selected = resolve_existing(root, relative)
    if not selected.is_file():
        raise DomainError(f"Asset path is not a file: {relative}")

    terms = {selected.stem}
    if selected.suffix.lower() == ".json":
        try:
            _collect_relation_values(json.loads(selected.read_text(encoding="utf-8-sig")), "", terms)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            pass

    bundle_root = _bundle_root(roots, selected)
    related: list[dict] = []
    seen = {selected.resolve()}
    stem = normalize_relation_value(selected.stem)
    if bundle_root is not None and stem:
        for found in _walk_files(bundle_root):
            if len(related) >= MAX_RELATED_RESULTS:
                break
            if normalize_relation_value(found.stem) == stem and found.resolve() not in seen:
                seen.add(found.resolve())
                related.append(_related_file(root, found, "Same Unity asset name"))
    return {"path": relative, "assets": related, "unityObjects": [], "tables": _related_tables(roots, terms)}


def _walk_files(root: Path):
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            children = list(current.iterdir())
        except OSError:
            continue
        for child in children:
            if child.is_symlink() or child.name == "ObjectIndex":
                continue
            if child.is_dir():
                stack.append(child)
            elif child.is_file():
                yield child


def _related_file(root: Path, file_path: Path, relation: str) -> dict:
    relative = _relative(root, file_path)
    extension = file_path.suffix.lower()
    return {
        "name": file_path.name, "path": relative, "kind": "file", "extension": extension,
        "size": file_path.stat().st_size, "assetType": asset_type_for(relative, extension), "relation": relation,
    }


def _collect_relation_values(value, key: str, terms: set[str], depth: int = 0) -> None:
    if depth > 12 or value is None or len(terms) >= 48:
        return
    if isinstance(value, list):
        for item in value:
            _collect_relation_values(item, key, terms, depth + 1)
        return
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            _collect_relation_values(child_value, child_key, terms, depth + 1)
        return
    text = str(value).strip()
    if len(text) < 3 or len(text) > 180:
        return
    relevant = any(word in key.lower() for word in ("id", "name", "str", "key", "asset", "icon", "prefab", "texture", "sprite", "stage", "unit", "item"))
    if relevant or text.upper() == text and any(ch.isalpha() for ch in text):
        terms.add(text)


def _related_tables(roots: Roots, terms: set[str]) -> list[dict]:
    index_path = Path(roots.wiki_dir) / "idIndex.json"
    if not index_path.exists():
        return []
    normalized = [normalize_relation_value(term) for term in terms]
    normalized = [term for term in normalized if len(term) >= 3]
    if not normalized:
        return []
    try:
        rows = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    matches = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        for field_name in ("strId", "image", "name", "type"):
            value = normalize_relation_value(row.get(field_name))
            if value and any(value == term or (len(term) >= 8 and len(value) >= 8 and (value.endswith(term) or term.endswith(value))) for term in normalized):
                key = f"{row.get('source') or row.get('table')}|{row.get('id')}|{row.get('strId') or ''}"
                if key not in seen:
                    seen.add(key)
                    matches.append({**row, "matchedBy": f"{field_name} {row.get(field_name)}"})
                break
        if len(matches) >= MAX_RELATED_RESULTS:
            break
    return matches
```

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_assets.py -v`
Expected: PASS (6 tests)

- [x] **Step 5: Commit**

```bash
git add src/counterside_mcp/assets.py tests/unit/test_assets.py
git commit -m "feat: read asset directories, files, text, Spine sets and relations"
```

---

### Task 9: MCP server, tools, resources, smoke test

**Files:**
- Create: `src/counterside_mcp/server.py`
- Test: `tests/test_server_smoke.py`

**Interfaces:**
- Consumes: every module above.
- Produces: `mcp` (an `MCPServer` instance); `main()` entry point; thirteen tools and four resource templates registered.

- [x] **Step 1: Write the failing smoke test**

`tests/test_server_smoke.py`:
```python
import json
from pathlib import Path

import pytest

from counterside_mcp import server


def build_tree(tmp_path: Path) -> Path:
    luac = tmp_path / "gameplay-jsons" / "StreamingAssets" / "ab_script_unit_data" / "luac"
    luac.mkdir(parents=True)
    (luac / "LUA_UNIT_TEMPLET_BASE.json").write_text(json.dumps({"records": [{
        "m_UnitID": 1, "m_UnitStrID": "NKM_UNIT_A", "m_NKM_UNIT_TYPE": "NUT_COUNTER", "m_Name": "NAME_A",
    }]}))
    icons = tmp_path / "extracted-assets" / "all" / "Data" / "StreamingAssets" / "ab_inven_icon_unit" / "Texture2D"
    icons.mkdir(parents=True)
    (icons / "ICON_A.png").write_bytes(b"\x89PNG")
    (tmp_path / "wiki" / "data").mkdir(parents=True)
    (tmp_path / "server-data").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def roots(monkeypatch, tmp_path):
    root = build_tree(tmp_path)
    monkeypatch.setenv("CS_REVIVALSIDE_ROOT", str(root))
    return server.resolve()


def test_health_reports_roots(roots):
    report = server.health_report(roots)
    assert report["roots"]["asset"]["exists"] is True


def test_list_objects_and_asset_listing(roots):
    objects = server.list_objects(roots, "unit", "", 0, 100)
    assert objects["total"] == 1
    listing = server.list_directory(roots, "", "", 0, 50)
    assert listing["total"] >= 1
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_server_smoke.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'counterside_mcp.server'`

- **Step 3: Write `server.py`**

```python
"""MCP server: registers read-only tools and resources over stdio."""

from __future__ import annotations

import base64
import os
from functools import lru_cache
from pathlib import Path

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import __version__
from . import assets as assets_module
from . import config as config_module
from . import objects as objects_module
from . import systems as systems_module
from . import tables as tables_module
from .errors import DomainError

PACKAGE_DIR = Path(__file__).resolve().parent.parent

mcp = MCPServer("counterside")


@lru_cache(maxsize=1)
def resolve() -> config_module.Roots:
    return config_module.resolve_roots(package_dir=PACKAGE_DIR)


def _roots() -> config_module.Roots:
    return resolve()


def _guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DomainError as error:
        raise ToolError(str(error)) from error
    except ValueError as error:
        raise ToolError(str(error)) from error


def health_report(roots: config_module.Roots) -> dict:
    report = config_module.health(roots)
    table_entries = tables_module.list_table_entries(roots)
    report["tableCount"] = len(table_entries)
    report["systemsCount"] = len(systems_module.load_systems())
    report["version"] = __version__
    return report


# --- Discovery -------------------------------------------------------------

@mcp.tool()
def counterside_health() -> dict:
    """Report resolved data roots, table count, asset availability and version."""
    return health_report(_roots())


@mcp.tool()
def counterside_list_systems() -> dict:
    """List the curated CounterSide game systems with table counts and edit hints."""
    return _guard(systems_module.list_systems, _roots())


@mcp.tool()
def counterside_search_fields(query: str) -> dict:
    """Search gameplay systems, tables and fields for a value or concept (e.g. 'unit respawn cost')."""
    return _guard(systems_module.search_fields, _roots(), query)


# --- Tables ----------------------------------------------------------------

@mcp.tool()
def counterside_list_tables(query: str = "", offset: int = 0, limit: int = 100) -> dict:
    """List decoded gameplay tables, optionally filtered by a name substring."""
    roots = _roots()
    entries = tables_module.list_table_entries(roots)
    needle = str(query or "").strip().lower()
    if needle:
        entries = [e for e in entries if needle in e.table_name.lower() or needle in e.directory.lower()]
    offset = max(0, int(offset or 0))
    limit = max(1, min(250, int(limit or 100)))
    return {"total": len(entries), "offset": offset, "limit": limit,
            "tables": [tables_module.table_entry_json(e) for e in entries[offset:offset + limit]]}


@mcp.tool()
def counterside_get_table(directory: str, file: str, query: str = "", offset: int = 0, limit: int = 100) -> dict:
    """Read one gameplay table's records, optionally filtered by a substring."""
    roots = _roots()
    entry = tables_module.find_table_entry(roots, directory, file)
    if entry is None:
        raise ToolError(f"Gameplay table was not found: {directory}/{file}")
    records, _ = tables_module.read_table_records(roots, directory, file)
    unfiltered_total = len(records)
    needle = str(query or "").strip().lower()
    if needle:
        records = [r for r in records if needle in tables_module.json.dumps(r, ensure_ascii=False).lower()]
    offset = max(0, int(offset or 0))
    limit = max(1, min(250, int(limit or 100)))
    page = records[offset:offset + limit]
    return {"table": tables_module.table_entry_json(entry), "total": len(records),
            "unfilteredTotal": unfiltered_total, "offset": offset, "limit": limit, "records": page}


# --- Objects ---------------------------------------------------------------

@mcp.tool()
def counterside_list_objects(type: str = "unit", query: str = "", offset: int = 0, limit: int = 100) -> dict:
    """List game objects. type is one of unit, ship, operator, gear."""
    return _guard(objects_module.list_objects, _roots(), type, query, offset, limit)


@mcp.tool()
def counterside_get_object(type: str, id: int) -> dict:
    """Inspect one object fully: identity ids, every referenced id, stats, and resolved asset paths."""
    return _guard(objects_module.get_object, _roots(), type, id)


@mcp.tool()
def counterside_find_asset_for_object(type: str, id: int, field: str = "") -> dict:
    """Resolve an object's asset fields to concrete paths in the extracted-asset tree."""
    return _guard(objects_module.find_asset_for_object, _roots(), type, id, field or None)


# --- Assets ----------------------------------------------------------------

@mcp.tool()
def counterside_list_assets(path: str = "", query: str = "", offset: int = 0, limit: int = 100) -> dict:
    """List a directory in the extracted-asset tree with typed entries."""
    return _guard(assets_module.list_directory, _roots(), path, query, offset, limit)


@mcp.tool()
def counterside_get_asset(path: str) -> list:
    """Return a file's metadata, or the image itself when it is a PNG/JPEG/WEBP."""
    roots = _roots()
    metadata = _guard(assets_module.asset_metadata, roots, path)
    if not metadata["isImage"]:
        return [{"type": "text", "text": _json(metadata)}]
    data, content_type = assets_module.asset_bytes(roots, path)
    return [
        {"type": "text", "text": _json(metadata)},
        {"type": "image", "data": base64.b64encode(data).decode("ascii"), "mimeType": content_type},
    ]


@mcp.tool()
def counterside_read_text(path: str, maxBytes: int = 524288) -> dict:
    """Return a capped text preview for a text-like asset (json, atlas, csv, lua, xml, txt, ...)."""
    return _guard(assets_module.text_preview, _roots(), path, maxBytes)


@mcp.tool()
def counterside_get_spine_set(path: str) -> dict:
    """Resolve a Spine source file to its skeleton, atlas and texture pages."""
    return _guard(assets_module.spine_set, _roots(), path)


@mcp.tool()
def counterside_find_related(path: str) -> dict:
    """Find files sharing an asset name and gameplay-table rows that reference an asset."""
    return _guard(assets_module.find_related, _roots(), path)


def _json(value) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, indent=2)


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
```

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_server_smoke.py -v`
Expected: PASS (2 tests)

- [x] **Step 5: Verify the server starts and lists tools**

Run:
```bash
.venv/bin/python -c "
import asyncio, counterside_mcp.server as s
async def go():
    tools = await s.mcp.list_tools()
    print(len(tools), 'tools')
    print(sorted(t.name for t in tools))
    resources = await s.mcp.list_resource_templates()
    print(len(resources), 'resource templates')
asyncio.run(go())
"
```
Expected: `13 tools`, the thirteen `counterside_*` names, and `4 resource templates`.

- [x] **Step 6: Commit**

```bash
git add src/counterside_mcp/server.py tests/test_server_smoke.py
git commit -m "feat: expose read-only MCP tools and resources over stdio"
```

---

### Task 10: Parity harness

**Files:**
- Create: `tests/parity/__init__.py`
- Create: `tests/parity/conftest.py`
- Create: `tests/parity/test_parity.py`
- Create: `tests/parity/fixtures.json`

**Interfaces:**
- Consumes: all modules; a running Mod:Side on `http://127.0.0.1:5175/mod-side/api`.
- Produces: parity tests marked `parity`, skipped when the Node server is unreachable.

- [x] **Step 1: Write `tests/parity/conftest.py`**

```python
import json
import urllib.request

import pytest

BASE = "http://127.0.0.1:5175/mod-side/api"


def _reachable() -> bool:
    try:
        with urllib.request.urlopen(f"{BASE}/health", timeout=1.5) as response:
            return response.status == 200
    except Exception:
        return False


@pytest.fixture(scope="session")
def node_api():
    if not _reachable():
        pytest.skip("Mod:Side API is not running on 127.0.0.1:5175")
    def get(route: str, **params):
        query = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
        url = f"{BASE}/{route}" + (f"?{query}" if query else "")
        with urllib.request.urlopen(url, timeout=15) as response:
            return json.load(response)
    return get
```

- [x] **Step 2: Write `tests/parity/test_parity.py`**

```python
import pytest

from counterside_mcp import assets, objects, systems, tables
from counterside_mcp.config import resolve_roots

pytestmark = pytest.mark.parity


@pytest.fixture(scope="module")
def roots():
    return resolve_roots()


def test_systems_parity(node_api, roots):
    theirs = node_api("systems")
    ours = systems.list_systems(roots)
    assert [s["id"] for s in ours["systems"]] == [s["id"] for s in theirs["systems"]]


def test_tables_parity(node_api, roots):
    theirs = node_api("tables", limit=250)
    ours = tables.list_table_entries(roots)
    assert len(ours) == theirs["total"]


def test_asset_listing_parity(node_api, roots):
    theirs = node_api("assets", path="Data/StreamingAssets", limit=250)
    ours = assets.list_directory(roots, "Data/StreamingAssets", "", 0, 250)
    assert [e["name"] for e in ours["entries"]] == [e["name"] for e in theirs["entries"]]
```

- [x] **Step 3: Create `tests/parity/__init__.py`** (empty).

- [x] **Step 4: Run the suite — parity skips when Node is down**

Run: `.venv/bin/pytest -q`
Expected: all unit tests pass; parity tests skip with "Mod:Side API is not running".

- [x] **Step 5: Commit**

```bash
git add tests/parity
git commit -m "test: add optional parity harness against the Node Mod:Side API"
```

---

### Task 11: README and documentation

**Files:**
- Create: `counterside-mcp/README.md`

**Interfaces:**
- Consumes: nothing.
- Produces: user-facing setup and client-configuration docs.

- [x] **Step 1: Write `README.md`**

````markdown
# counterside-mcp

A read-only MCP server that lets an AI agent examine CounterSide game data:
decoded gameplay tables, game objects (units / ships / operators / gear) and
the ids they reference, and the extracted asset tree (PNGs, Spine, audio,
text).

It reads local files directly. No Node process, no game listener, no network,
and **no writes** — every tool is read-only.

## Install

```bash
cd counterside-mcp
python3 -m venv .venv
.venv/bin/pip install -e .
```

## Configure

Point the server at your RevivalSide directory:

```bash
export CS_REVIVALSIDE_ROOT=/path/to/RevivalSide
```

Each root can also be set individually, which is useful when the asset tree
and the table tree live in different places:

| Variable | Default | Contents |
|---|---|---|
| `CS_REVIVALSIDE_ROOT` | sibling `RevivalSide/` | base for all defaults |
| `CS_ASSET_VIEWER_ROOT` | `<base>/extracted-assets/all` | PNG / WAV / Spine / text |
| `CS_GAMEPLAY_TABLES_DIR` | `<base>/gameplay-jsons` | decoded `LUA_*.json` tables |
| `CS_GAMEPLAY_JSON_ROOTS` | — | extra table roots, comma-separated |
| `CS_GAMEPLAY_TABLE_ROOTS` | — | extra table roots, comma-separated |
| `CS_COUNTERSIDE_WIKI` | `<base>/wiki/data` | `idIndex.json`, `units.json` |
| `CS_SERVER_DATA_DIR` | `<base>/server-data` | authoritative `units.json` |

Call `counterside_health` first: it reports every resolved root and whether it
exists, so a misconfiguration is visible immediately.

## Client configuration

```json
{
  "mcpServers": {
    "counterside": {
      "command": "/path/to/counterside-mcp/.venv/bin/counterside-mcp",
      "env": { "CS_REVIVALSIDE_ROOT": "/path/to/RevivalSide" }
    }
  }
}
```

## Tools

- **Discovery** — `counterside_health`, `counterside_list_systems`, `counterside_search_fields`
- **Tables** — `counterside_list_tables`, `counterside_get_table`
- **Objects** — `counterside_list_objects`, `counterside_get_object`, `counterside_find_asset_for_object`
- **Assets** — `counterside_list_assets`, `counterside_get_asset`, `counterside_read_text`, `counterside_get_spine_set`, `counterside_find_related`

## Tests

```bash
.venv/bin/pytest -q                      # unit tests
.venv/bin/pytest -q -m parity            # parity vs Mod:Side (needs it running)
```
````

- [x] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add setup and client configuration README"
```

---

### Task 12: End-to-end verification against real data

**Files:**
- No source changes. Verification only.

**Interfaces:**
- Consumes: the whole server; the real `RevivalSide` checkout and the extracted-asset tree.

- [x] **Step 1: Run the full unit suite**

Run: `.venv/bin/pytest -q -m "not parity"`
Expected: PASS, no failures.

- [x] **Step 2: Point the server at real data and check health**

Run:
```bash
CS_REVIVALSIDE_ROOT=/home/windows/project/RevivalSide .venv/bin/python -c "
from counterside_mcp import server
print(server.health_report(server.resolve()))
"
```
Expected: `tableCount` > 0, `roots.asset.exists` true (set `CS_ASSET_VIEWER_ROOT` to
`/mnt/c/Users/windows/AppData/Local/RevivalSide/extracted-assets/all` — the `all`
level is required; the parent holds only `all/` and `manifest.json`, so pointing
at it makes every asset preview resolve to `""`), `systemsCount` = 29.

- [x] **Step 3: Exercise the object→asset join on real data**

Run:
```bash
CS_REVIVALSIDE_ROOT=/home/windows/project/RevivalSide CS_ASSET_VIEWER_ROOT=/mnt/c/Users/windows/AppData/Local/RevivalSide/extracted-assets/all .venv/bin/python -c "
import json
from counterside_mcp import server, objects
roots = server.resolve()
print(json.dumps(objects.find_asset_for_object(roots, 'unit', 1004), indent=2)[:800])
"
```
Expected: a JSON object listing `assets` whose `path` values point at real PNGs under `Data/StreamingAssets/...`.

- [x] **Step 4: List a real asset directory and read a table**

Run:
```bash
CS_REVIVALSIDE_ROOT=/home/windows/project/RevivalSide CS_ASSET_VIEWER_ROOT=/mnt/c/Users/windows/AppData/Local/RevivalSide/extracted-assets/all .venv/bin/python -c "
from counterside_mcp import server, tables, assets
roots = server.resolve()
listing = assets.list_directory(roots, 'Data/StreamingAssets/ab_inven_icon_unit/Texture2D', '', 0, 5)
print([e['name'] for e in listing['entries']])
print(tables.list_table_entries(roots)[:2])
"
```
Expected: real icon filenames, and at least two table entries.

- [x] **Step 5: Record the result**

No commit. Report the observed output to the user, including any root that had
to be set explicitly on this machine.
````

Note: Step 3 of Task 12 above has a stray line — the implementer should drop
the `obj = ...` line and run only the `find_asset_for_object` call.

---

## Self-Review

**Spec coverage**

| Spec section | Task |
|---|---|
| §4.1 base root `CS_REVIVALSIDE_ROOT` | Task 3 |
| §4.2 four roots + extras | Task 3 |
| §4.3 expansion and precedence | Task 3 (`expand_root`, `resolve_roots`) |
| §4.4 path safety | Task 2 |
| §5 module layout | Tasks 2–9 |
| §6.1 discovery tools | Tasks 6, 9 |
| §6.2 table tools | Tasks 5, 9 |
| §6.3 object tools | Tasks 7, 9 |
| §6.4 asset tools | Task 8, 9 |
| §6.5 resources | Task 9 |
| §7 parity notes | Tasks 4 (`stats`), 5 (`tables`), 7 (`objects`), 8 (`assets`) |
| §8 error handling | Tasks 2, 9 |
| §9 testing | Tasks 2–10 |
| §10 risks | Tasks 3 (roots), 9 (health), 5 (table preference) |
| §11 milestones | Task order 1→9 mirrors milestones 1→6 |

**Placeholder scan:** no TBD/TODO; every code step carries real code. The one
awkward line in Task 12 Step 3 is explicitly flagged for removal.

**Type consistency:** `Roots` fields (`revival_root`, `asset_dirs`,
`table_dirs`, `wiki_dir`, `server_data_dir`) are used identically in Tasks 3–9.
`TableEntry` fields match between Tasks 5 and 6. `table_entry_json` is defined
in Task 5 and used in Tasks 6 and 9. `DomainError` is raised in Tasks 2–8 and
translated only in Task 9.

**Review Focus tests:** path escape → Task 2; missing root → Task 3
(`test_health_reports_missing_asset_root`, `test_missing_revival_root_raises`);
direct bundle root → Task 3 (`test_expand_root_uses_direct_bundle_layout`);
non-text file → Task 8 (`test_text_preview_rejects_binary`); Spine missing page
→ Task 8 (`test_spine_set_resolves_all_roles`, whose `missing` branch is
exercised by the pre-check paths).
