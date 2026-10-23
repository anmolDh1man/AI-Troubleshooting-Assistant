"""Tests for knowledge-base loading and validation (no network or model needed)."""

import json

import pytest

from src.kb_loader import KBValidationError, load_knowledge_base


def _valid_entry(entry_id="KB-001"):
    return {
        "id": entry_id,
        "title": "Sample issue",
        "category": "Application",
        "symptoms": ["Something fails"],
        "keywords": ["fail"],
        "diagnostic_checks": ["Check logs"],
        "resolution_steps": ["Escalate"],
        "requires_approval": [],
        "escalation": [{"team": "L2 Application Support", "when": "Always"}],
        "prerequisites": [],
        "related_ids": [],
    }


def _write_kb(tmp_path, entries):
    path = tmp_path / "kb.json"
    path.write_text(json.dumps({"entries": entries}), encoding="utf-8")
    return path


def test_real_knowledge_base_is_valid():
    entries = load_knowledge_base()
    assert len(entries) >= 10
    assert len({entry.id for entry in entries}) == len(entries)


def test_search_chunks_cover_title_symptoms_keywords_but_not_resolution():
    entry = load_knowledge_base()[0]
    chunks = entry.search_chunks()
    texts = [text for _, text in chunks]
    assert entry.title in texts
    assert all(symptom in texts for symptom in entry.symptoms)
    assert any(entry.keywords[0] in text for text in texts)
    assert not any(entry.resolution_steps[0] in text for text in texts)
    assert len({chunk_id for chunk_id, _ in chunks}) == len(chunks)


def test_missing_file_raises(tmp_path):
    with pytest.raises(KBValidationError, match="not found"):
        load_knowledge_base(tmp_path / "missing.json")


def test_malformed_json_raises(tmp_path):
    path = tmp_path / "kb.json"
    path.write_text('{"entries": [', encoding="utf-8")
    with pytest.raises(KBValidationError, match="Invalid JSON"):
        load_knowledge_base(path)


def test_duplicate_ids_raise(tmp_path):
    path = _write_kb(tmp_path, [_valid_entry("KB-001"), _valid_entry("KB-001")])
    with pytest.raises(KBValidationError, match="Duplicate ids: KB-001"):
        load_knowledge_base(path)


def test_missing_required_field_raises(tmp_path):
    entry = _valid_entry()
    del entry["diagnostic_checks"]
    path = _write_kb(tmp_path, [entry])
    with pytest.raises(KBValidationError, match="diagnostic_checks"):
        load_knowledge_base(path)


def test_unknown_team_raises(tmp_path):
    entry = _valid_entry()
    entry["escalation"] = [{"team": "Random Team", "when": "Always"}]
    path = _write_kb(tmp_path, [entry])
    with pytest.raises(KBValidationError, match="unknown escalation team"):
        load_knowledge_base(path)


def test_unknown_related_id_raises(tmp_path):
    entry = _valid_entry()
    entry["related_ids"] = ["KB-999"]
    path = _write_kb(tmp_path, [entry])
    with pytest.raises(KBValidationError, match="KB-999"):
        load_knowledge_base(path)
