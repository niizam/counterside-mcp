"""Curated game systems and field search.

The system table is data, copied verbatim from ``GAME_SYSTEMS`` in
``server/assetViewer.js`` by ``tools/extract_systems.cjs``.
"""

import json
from dataclasses import dataclass, field
from importlib import resources

from .config import Roots
from .stats import normalize_search_token, tokenize
from .tables import (
    TableEntry,
    list_table_entries,
    records_for_entry,
    table_entry_json,
    table_schema,
)

# Everyday words an agent is likely to use, mapped onto the table vocabulary.
FIELD_ALIASES = {
    "hp": ["health", "nsthp"],
    "health": ["hp", "nsthp"],
    "attack": ["atk", "damage", "nstatk", "atkfactor"],
    "atk": ["attack", "damage", "nstatk", "atkfactor"],
    "defense": ["def", "nstdef", "armor"],
    "defence": ["def", "nstdef", "armor"],
    "speed": ["movespeed", "attackspeed"],
    "cooldown": ["cooltime", "cooltimereduce"],
    "critical": ["crit", "criticaldamage"],
    "crit": ["critical", "criticaldamage"],
    "evasion": ["evade"],
    "evade": ["evasion"],
    "accuracy": ["hit"],
    "deploy": ["respawn", "cost"],
    "cost": ["price", "count", "eternium", "credit", "respawn"],
    "reward": ["drop", "rewardvalue", "rewardid"],
    "drop": ["reward", "droprate", "dropid"],
    "level": ["levelup", "perlevel", "maxlevel"],
    "experience": ["exp"],
    "exp": ["experience"],
    "duration": ["lifetime", "time", "timemax"],
    "range": ["attackrange", "distance"],
    "stage": ["dungeon", "episode"],
    "unit": ["character"],
}

MAX_FIELD_TABLES = 12
MAX_FIELD_RESULTS = 60
MAX_MATCHED_SYSTEMS = 3
PHRASE_BONUS = 12
PREFIX_BONUS = 4
PRIORITY_BONUS = 20


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
    with resources.files("counterside_mcp.data").joinpath("systems.json").open(
        encoding="utf-8"
    ) as handle:
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
    """Tables belonging to a system: a '*' directory means every table."""
    if "*" in system.directories:
        return list(entries)
    return [
        entry
        for entry in entries
        if entry.directory in system.directories
        or any(entry.table_name.startswith(prefix) for prefix in system.prefixes)
    ]


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
    return {
        "tableCount": len(entries),
        "systems": [public_system(system, entries) for system in load_systems()],
    }


def system_search_text(system: GameSystem) -> str:
    edits = " ".join(
        f"{edit.get('label', '')} {edit.get('query', '')} {edit.get('location', '')}"
        for edit in system.common_edits
    )
    return " ".join([system.title, system.description, *system.keywords, edits]).lower()


def _score(value: str, term_list: list[str]) -> int:
    """Longer term matches score higher, so specific queries outrank vague ones."""
    lowered = str(value or "").lower()
    normalized = normalize_search_token(value)
    return sum(
        max(1, len(term)) for term in term_list if term in lowered or normalize_search_token(term) in normalized
    )


def _system_for(table: TableEntry, systems: list[GameSystem]) -> GameSystem | None:
    for system in systems:
        if system.id != "all" and system_tables(system, [table]):
            return system
    return None


def _candidate_score(table: TableEntry, term_list: list[str], phrase: str) -> int:
    """Score a table name. Cheap, so every discovered table can be ranked."""
    lowered = table.table_name.lower()
    score = _score(lowered, term_list)
    if phrase and phrase in lowered:
        score += PHRASE_BONUS
    for term in term_list:
        if len(term) >= 4 and lowered.startswith(term):
            score += PREFIX_BONUS
    return score


def _field_score(path: str, term_list: list[str], phrase: str) -> int:
    """Score one field path on its own name.

    Only the field's own path counts: a term the field merely shares through its
    table's name says nothing about the field, and letting those in makes every
    field in a big table look alike.
    """
    lowered = path.lower()
    score = 0
    for term in term_list:
        if term in lowered:
            score += max(1, len(term))
    if phrase and phrase in lowered:
        score += PHRASE_BONUS
    return score


def search_fields(roots: Roots, query: str) -> dict:
    """Rank systems, tables and fields for a plain-language query."""
    query = str(query or "").strip()
    if len(query) < 2:
        raise ValueError("Describe the value you want to change (at least two characters).")

    entries = list_table_entries(roots)
    phrase = query.lower()
    terms = set(tokenize(query))
    for term in list(terms):
        terms.update(FIELD_ALIASES.get(term, []))
    # The whole normalized query is a useful term only when it is a single word;
    # otherwise it is a phrase, handled by the phrase bonus.
    compact = normalize_search_token(query)
    if compact and " " not in query:
        terms.add(compact)
    term_list = [term for term in terms if term]

    systems = load_systems()
    scored_systems = sorted(
        (
            (system, _score(system_search_text(system), term_list) * 10)
            for system in systems
            if system.id != "all"
        ),
        key=lambda pair: pair[1],
        reverse=True,
    )
    scored_systems = [pair for pair in scored_systems if pair[1] > 0]

    # A system's curated priorityTables are the strongest hint available for
    # "which table actually holds this", and they must not be crowded out by the
    # arbitrary alphabetical head of a large system's table list.
    priority_keys = set()
    for system, _ in scored_systems[:MAX_MATCHED_SYSTEMS]:
        wanted = {name.upper() for name in system.priority_tables}
        priority_keys.update(
            _entry_key(entry) for entry in entries if entry.table_name.upper() in wanted
        )

    ranked_tables: list[tuple[TableEntry, int]] = []
    for entry in entries:
        score = _candidate_score(entry, term_list, phrase)
        if _entry_key(entry) in priority_keys:
            score += PRIORITY_BONUS
        if score > 0:
            ranked_tables.append((entry, score))
    ranked_tables.sort(key=lambda item: (-item[1], item[0].relative_path))
    ranked_tables = ranked_tables[:MAX_FIELD_TABLES]

    fields = []
    for table, table_score in ranked_tables:
        for schema_field in table_schema(records_for_entry(table)):
            path = schema_field["path"]
            score = _field_score(path, term_list, phrase)
            if not score:
                continue
            fields.append(
                {
                    **schema_field,
                    # Rank on the field's own name; the table's score only
                    # breaks ties between equally good field names.
                    "score": score,
                    "tableScore": table_score,
                    "system": _system_title_for(table, systems),
                    "table": table_entry_json(table),
                }
            )
    fields.sort(key=lambda item: (-item["score"], -item["tableScore"], item["path"]))

    return {
        "query": query,
        "systems": [
            {**public_system(system, entries), "score": score}
            for system, score in scored_systems[:5]
        ],
        "tables": [
            {**table_entry_json(table), "score": score, "system": _system_title_for(table, systems)}
            for table, score in ranked_tables
        ],
        "fields": fields[:MAX_FIELD_RESULTS],
    }


def _entry_key(entry: TableEntry) -> str:
    return f"{entry.directory.lower()}/{entry.table_name.lower()}"


def _system_title_for(table: TableEntry, systems: list[GameSystem]) -> str:
    system = _system_for(table, systems)
    return system.title if system else "Gameplay data"
