"""Tests for error-signature normalisation (src/error_signatures.py). No model needed."""

import pytest

from src.error_signatures import (
    SignatureIndex, detect_signatures, drop_negated_symptoms, expand_for_retrieval, rerank_by_signature,
)
from src.kb_loader import load_knowledge_base
from src.retriever import RetrievalResult


@pytest.mark.parametrize("text, signature", [
    ("getaddrinfo EAI_AGAIN api.bank.example", "dns_failure"),
    ("java.net.UnknownHostException: ledger-svc", "dns_failure"),
    ("dig returned SERVFAIL for the gateway domain", "dns_failure"),
    ("dial tcp: lookup orders-db: no such host", "dns_failure"),
    ("curl: (6) Could not resolve host: psp.example", "dns_failure"),
    ("connect ECONNREFUSED 10.1.2.3:443", "connection_refused"),
    ("java.net.ConnectException: Connection refused", "connection_refused"),
    ("read ECONNRESET from the issuer link", "connection_reset"),
    ("ETIMEDOUT while calling the risk engine", "timeout"),
    ("java.net.SocketTimeoutException: Read timed out", "timeout"),
    ("FATAL: sorry, too many clients already", "db_too_many_connections"),
    ("ORA-12519: TNS no appropriate service handler found", "db_too_many_connections"),
    ("Deadlock found when trying to get lock", "db_lock"),
    ("Lock wait timeout exceeded on the refunds table", "db_lock"),
    ("ORA-00060: deadlock detected", "db_lock"),
    # Phase 3 completion: verb form of "connection refused" (P31) and connection-pool questions (P23)
    ("the API isn't slow, it just refuses connections", "connection_refused"),
    ("the ledger service refused all connections overnight", "connection_refused"),
    ("can we change the connection pool size?", "db_connection_pool"),
    ("connection-pool metrics look odd", "db_connection_pool"),
])
def test_known_error_strings_are_recognised(text, signature):
    assert signature in detect_signatures(text)


@pytest.mark.parametrize("text", [
    "The payment API is returning a 500 error",
    "merchant user is locked out of the portal",
    "the rate of card declines doubled",
    "settlement file was not generated",
    "HikariCP says connection is not available, request timed out after 30000ms",  # E04 must stay untouched
    "API responses are slow today",
    "",
])
def test_ordinary_text_is_not_expanded(text):
    expanded, names = expand_for_retrieval(text)
    assert names == [] and expanded == text


def test_expansion_keeps_the_original_text_first():
    expanded, names = expand_for_retrieval("EAI_AGAIN when calling the bank")
    assert expanded.startswith("EAI_AGAIN when calling the bank. ")
    assert "DNS name resolution failure" in expanded and names == ["dns_failure"]


@pytest.mark.parametrize("text, expected", [
    ("the API isn't slow, it just refuses connections", "the API is it just refuses connections"),
    ("payments are not stuck in pending, they fail instantly", "payments are they fail instantly"),
    ("the gateway is no longer timing out but returns 500", "the gateway is"),
    ("checkout is not slow", "checkout is"),
])
def test_negated_symptoms_are_dropped(text, expected):
    assert drop_negated_symptoms(text) == expected


@pytest.mark.parametrize("text", [
    "the checkout API is slow and sometimes times out",   # no negation
    "webhook not received for paid orders",               # "received" is not a listed symptom
    "settlement file was not generated",
    "API is not responding",
    "not slow",                                           # nothing would be left: unchanged
])
def test_other_text_is_kept(text):
    assert drop_negated_symptoms(text) == text


@pytest.mark.parametrize("text, name", [
    ("the API isn't slow, it just refuses connections", "connection_refused"),
    ("can we change the connection pool size?", "db_connection_pool"),
])
def test_rerank_only_signatures_do_not_change_the_search_text(text, name):
    expanded, names = expand_for_retrieval(text)
    assert expanded == text and names == [name]


def test_signature_index_is_derived_from_kb_text():
    index = SignatureIndex(load_knowledge_base())
    assert "connection_refused" in index.by_entry["KB-007"]       # "Errors such as 'connection refused' ..."
    assert "connection_refused" in index.by_entry["KB-003"]
    assert "db_connection_pool" in index.by_entry["KB-003"]
    assert "db_lock" in index.by_entry["KB-013"]
    assert not index.by_entry["KB-011"]                           # payment-flow entry has no error signature


def _results(*scored):
    entries = {e.id: e for e in load_knowledge_base()}
    return [RetrievalResult(entries[i], s, entries[i].title) for i, s in scored]


def test_rerank_by_signature_promotes_matching_entries_above_the_floor():
    index = SignatureIndex(load_knowledge_base())
    results = _results(("KB-011", 0.56), ("KB-002", 0.53), ("KB-007", 0.50), ("KB-010", 0.48))
    ranked = rerank_by_signature(results, ["connection_refused"], index, floor=0.30)
    assert [r.entry.id for r in ranked] == ["KB-007", "KB-011", "KB-002", "KB-010"]


def test_rerank_by_signature_respects_the_floor_and_needs_a_signature():
    index = SignatureIndex(load_knowledge_base())
    results = _results(("KB-011", 0.40), ("KB-007", 0.29))
    assert rerank_by_signature(results, ["connection_refused"], index, floor=0.30) == results
    assert rerank_by_signature(results, [], index, floor=0.30) == results


def test_multiple_signatures_are_all_appended():
    _, names = expand_for_retrieval("ECONNREFUSED then ETIMEDOUT on retry")
    assert names == ["connection_refused", "timeout"]
