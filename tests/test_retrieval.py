"""Retrieval tests. They load the local embedding model (no API key, no network after first download)."""

import pytest

from src.config import HIGH_CONFIDENCE_THRESHOLD, LOW_CONFIDENCE_THRESHOLD
from src.kb_loader import load_knowledge_base
from src.retriever import Retriever


@pytest.fixture(scope="module")
def retriever(tmp_path_factory):
    # Separate ChromaDB folder so tests never touch the app's index.
    return Retriever(load_knowledge_base(), persist_dir=tmp_path_factory.mktemp("chroma"))


def test_assignment_example_retrieves_payment_500_entry(retriever):
    results = retriever.search("The payment API is returning a 500 error")
    assert results[0].entry.id == "KB-001"
    assert results[0].score >= HIGH_CONFIDENCE_THRESHOLD


def test_paraphrase_without_shared_keywords_still_matches(retriever):
    results = retriever.search("customer was charged but order still shows unpaid")
    assert results[0].entry.id == "KB-011"


def test_off_topic_query_scores_below_low_threshold(retriever):
    results = retriever.search("what is the weather in Pune")
    assert results[0].score < LOW_CONFIDENCE_THRESHOLD


def test_results_are_distinct_sorted_and_limited(retriever):
    results = retriever.search("database connection refused", top_k=3)
    ids = [r.entry.id for r in results]
    scores = [r.score for r in results]
    assert len(results) == 3
    assert len(set(ids)) == 3
    assert scores == sorted(scores, reverse=True)


def test_matched_text_comes_from_the_returned_entry(retriever):
    result = retriever.search("no space left on device")[0]
    chunk_texts = [text for _, text in result.entry.search_chunks()]
    assert result.matched_text in chunk_texts


@pytest.mark.parametrize("query", [
    # Held-out eval case E04 failed in the Phase 5 baseline (retrieved KB-002, timeouts).
    "HikariCP says connection is not available, request timed out after 30000ms",
    # Real HikariCP log line format, not part of any evaluation set.
    "HikariPool-1 - Connection is not available, request timed out after 30000ms.",
])
def test_regression_hikaricp_pool_timeout_maps_to_database_entry(retriever, query):
    assert retriever.search(query)[0].entry.id == "KB-003"


def test_plain_request_timeout_still_maps_to_timeout_entry(retriever):
    # Guard: adding pool-timeout keywords to KB-003 must not pull generic timeouts away from KB-002.
    assert retriever.search("requests to the API are timing out after 30 seconds")[0].entry.id == "KB-002"


def test_empty_query_is_rejected(retriever):
    with pytest.raises(ValueError):
        retriever.search("   ")
