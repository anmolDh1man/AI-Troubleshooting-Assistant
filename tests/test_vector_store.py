"""Vector-store reliability and health checks (Phase 4). Uses the real model and temporary index folders."""

import pytest

from src.assistant import TroubleshootingAssistant
from src.health import run_health_checks
from src.kb_loader import load_knowledge_base
from src.retriever import COLLECTION_NAME, IndexUnavailableError, Retriever

ENTRIES = load_knowledge_base()


@pytest.fixture
def retriever(tmp_path):
    return Retriever(ENTRIES, persist_dir=tmp_path / "index")


def test_fresh_index_is_consistent(retriever):
    assert retriever.is_consistent()
    assert retriever.collection.count() == retriever.expected_chunks


def test_corrupt_index_folder_is_moved_aside_and_rebuilt(tmp_path):
    index = tmp_path / "index"
    index.mkdir()
    (index / "chroma.sqlite3").write_bytes(b"not a sqlite database" * 100)
    retriever = Retriever(ENTRIES, persist_dir=index)
    assert retriever.is_consistent()
    assert retriever.search("payment API returns 500", top_k=1)[0].entry.id == "KB-001"
    backups = [p for p in tmp_path.iterdir() if p.name.startswith("index.corrupt-")]
    assert len(backups) == 1 and (backups[0] / "chroma.sqlite3").exists()  # kept for investigation, not deleted


def test_incomplete_index_is_rebuilt_on_startup(tmp_path):
    first = Retriever(ENTRIES, persist_dir=tmp_path / "index")
    first.collection.delete(ids=[first.collection.get(limit=1)["ids"][0]])  # simulate a partial write
    assert not first.is_consistent()
    second = Retriever(ENTRIES, persist_dir=tmp_path / "index")
    assert second.is_consistent()


def test_collection_removed_while_running_is_rebuilt_once(retriever):
    retriever.client.delete_collection(COLLECTION_NAME)
    assert retriever.search("payment API returns 500", top_k=1)[0].entry.id == "KB-001"
    assert retriever.is_consistent()


def test_failed_rebuild_raises_index_unavailable(retriever, monkeypatch):
    retriever.client.delete_collection(COLLECTION_NAME)
    monkeypatch.setattr(retriever, "rebuild", lambda: (_ for _ in ()).throw(RuntimeError("disk full")))
    with pytest.raises(IndexUnavailableError):
        retriever.search("payment API returns 500")


def test_health_checks_pass_on_a_healthy_assistant(retriever):
    checks = run_health_checks(TroubleshootingAssistant(retriever))
    assert [c.name for c in checks] == ["configuration", "knowledge_base", "embedding_model", "vector_index",
                                        "match_indexes"]
    assert all(c.ok for c in checks), checks
    assert "384 dimensions" in checks[2].detail


def test_health_checks_report_an_inconsistent_index(retriever):
    assistant = TroubleshootingAssistant(retriever)
    retriever.collection.delete(ids=[retriever.collection.get(limit=1)["ids"][0]])
    checks = {c.name: c for c in run_health_checks(assistant)}
    assert not checks["vector_index"].ok and checks["knowledge_base"].ok


def test_health_check_failure_reports_only_the_exception_type(retriever, monkeypatch):
    assistant = TroubleshootingAssistant(retriever)
    monkeypatch.setattr(retriever.model, "encode", lambda *a, **k: (_ for _ in ()).throw(OSError("C:/secret/path")))
    checks = {c.name: c for c in run_health_checks(assistant)}
    assert not checks["embedding_model"].ok
    assert checks["embedding_model"].detail == "OSError while checking"
