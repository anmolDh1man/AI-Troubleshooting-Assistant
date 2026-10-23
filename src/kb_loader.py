"""Load and validate the troubleshooting knowledge base (data/knowledge_base.json)."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from src.config import KB_PATH

ALLOWED_TEAMS = {
    "L1 Operations / Command Center",
    "L2 Application Support",
    "Database Team",
    "Network Team",
    "DevOps / Infrastructure Team",
    "Security / IAM Team",
    "Payments Operations Team",
}
ID_PATTERN = re.compile(r"^KB-\d{3}$")

REQUIRED_TEXT_FIELDS = ("id", "title", "category")
NON_EMPTY_LIST_FIELDS = ("symptoms", "keywords", "diagnostic_checks", "resolution_steps")
OPTIONAL_LIST_FIELDS = ("requires_approval", "prerequisites", "related_ids")


class KBValidationError(Exception):
    """Raised when the knowledge base is missing, malformed, or contains invalid entries."""


@dataclass
class EscalationRule:
    team: str
    when: str


@dataclass
class KBEntry:
    id: str
    title: str
    category: str
    symptoms: list[str]
    keywords: list[str]
    diagnostic_checks: list[str]
    resolution_steps: list[str]
    requires_approval: list[str]
    escalation: list[EscalationRule]
    prerequisites: list[str]
    related_ids: list[str]

    def search_chunks(self) -> list[tuple[str, str]]:
        """Short texts that get embedded for retrieval, as (chunk_id, text) pairs.

        Users describe what they *see* (symptoms, error codes), not the fix,
        so only the title, each symptom, and the keywords are embedded.
        Each is a separate chunk: a short query matches a short symptom much
        better than one long block of text (measured in calibration).
        """
        chunks = [(f"{self.id}::title", self.title)]
        chunks += [(f"{self.id}::symptom-{i}", symptom) for i, symptom in enumerate(self.symptoms)]
        chunks.append((f"{self.id}::keywords", ", ".join(self.keywords)))
        return chunks


def _is_list_of_strings(value) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value)


def _validate_entry(raw: dict, position: int) -> list[str]:
    """Return a list of human-readable problems with one entry (empty list = valid)."""
    label = f"Entry #{position} ({raw.get('id', 'no id')})" if isinstance(raw, dict) else f"Entry #{position}"
    if not isinstance(raw, dict):
        return [f"{label}: must be a JSON object"]

    errors = []
    for field in REQUIRED_TEXT_FIELDS:
        if not isinstance(raw.get(field), str) or not raw[field].strip():
            errors.append(f"{label}: '{field}' must be a non-empty string")

    if isinstance(raw.get("id"), str) and not ID_PATTERN.match(raw["id"]):
        errors.append(f"{label}: id must look like 'KB-001'")

    for field in NON_EMPTY_LIST_FIELDS:
        if not _is_list_of_strings(raw.get(field)) or not raw[field]:
            errors.append(f"{label}: '{field}' must be a non-empty list of strings")

    for field in OPTIONAL_LIST_FIELDS:
        if field in raw and not _is_list_of_strings(raw[field]):
            errors.append(f"{label}: '{field}' must be a list of strings")

    escalation = raw.get("escalation")
    if not isinstance(escalation, list) or not escalation:
        errors.append(f"{label}: 'escalation' must be a non-empty list")
    else:
        for rule in escalation:
            if not isinstance(rule, dict) or not rule.get("team") or not rule.get("when"):
                errors.append(f"{label}: each escalation rule needs 'team' and 'when'")
            elif rule["team"] not in ALLOWED_TEAMS:
                errors.append(f"{label}: unknown escalation team '{rule['team']}'")

    return errors


def load_knowledge_base(path: Path = KB_PATH) -> list[KBEntry]:
    """Load, validate and return all knowledge-base entries.

    Collects every validation problem first and raises them together,
    so a broken KB file can be fixed in one pass.
    """
    path = Path(path)
    if not path.exists():
        raise KBValidationError(f"Knowledge base file not found: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise KBValidationError(f"Invalid JSON in {path.name} at line {exc.lineno}, column {exc.colno}: {exc.msg}") from exc

    raw_entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(raw_entries, list) or not raw_entries:
        raise KBValidationError("Knowledge base must contain a non-empty 'entries' list")

    errors = []
    for position, raw in enumerate(raw_entries, start=1):
        errors.extend(_validate_entry(raw, position))

    ids = [raw.get("id") for raw in raw_entries if isinstance(raw, dict)]
    duplicates = sorted({entry_id for entry_id in ids if ids.count(entry_id) > 1})
    if duplicates:
        errors.append(f"Duplicate ids: {', '.join(duplicates)}")

    known_ids = set(ids)
    for raw in raw_entries:
        if isinstance(raw, dict) and _is_list_of_strings(raw.get("related_ids", [])):
            for related in raw.get("related_ids", []):
                if related not in known_ids:
                    errors.append(f"{raw.get('id')}: related id '{related}' does not exist")

    if errors:
        raise KBValidationError("Knowledge base validation failed:\n  - " + "\n  - ".join(errors))

    return [
        KBEntry(
            id=raw["id"],
            title=raw["title"],
            category=raw["category"],
            symptoms=raw["symptoms"],
            keywords=raw["keywords"],
            diagnostic_checks=raw["diagnostic_checks"],
            resolution_steps=raw["resolution_steps"],
            requires_approval=raw.get("requires_approval", []),
            escalation=[EscalationRule(team=rule["team"], when=rule["when"]) for rule in raw["escalation"]],
            prerequisites=raw.get("prerequisites", []),
            related_ids=raw.get("related_ids", []),
        )
        for raw in raw_entries
    ]


if __name__ == "__main__":
    entries = load_knowledge_base()
    print(f"Loaded {len(entries)} valid entries from {KB_PATH.name}\n")
    for entry in entries:
        teams = ", ".join(rule.team for rule in entry.escalation)
        print(f"  {entry.id}  [{entry.category:<14}] {entry.title}")
        print(f"          escalation: {teams}")
    print("\nExample chunks (what gets embedded) for", entries[0].id)
    for chunk_id, text in entries[0].search_chunks():
        print(f"  {chunk_id:<20} {text}")
