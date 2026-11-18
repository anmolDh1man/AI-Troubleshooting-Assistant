"""Unit tests for HTTP status-code detection, the KB code index and code re-ranking (no model needed).

Sentences are written for this file; they are not copies of the probe sets or the sealed v3 cases.
"""

import pytest

from src.code_matching import CodeIndex, detect_http_codes, entry_codes, rerank_by_code
from src.kb_loader import load_knowledge_base
from src.retriever import RetrievalResult

ENTRIES = {entry.id: entry for entry in load_knowledge_base()}
INDEX = CodeIndex(ENTRIES.values())
RUPEE = chr(0x20B9)


def results(*scored):
    return [RetrievalResult(ENTRIES[entry_id], score, ENTRIES[entry_id].title) for entry_id, score in scored]


@pytest.mark.parametrize("text, codes", [
    ("HTTP 503 on checkout", {"503"}),
    ("the API fails immediately with 503", {"503"}),
    ("payments endpoint returns 500", {"500"}),
    ("lots of 503 errors since noon", {"503"}),
    ("504s", {"504"}),
    ("504", {"504"}),
    ("error 404 page on the merchant dashboard", {"404"}),
    ("status code 429 from the partner", {"429"}),
    ("404 not found on the refunds route", {"404"}),
    ("returned 502 bad gateway", {"502"}),
    ("HTTP 401 first, then HTTP 503 after the retry", {"401", "503"}),  # two codes in one query
    ("returns 500 and later 503 errors", {"500", "503"}),
    # Phase 2C.1: the three probe-5 misses and other wordings of the same patterns
    ("400 bad request when creating the order", {"400"}),            # reason phrase "bad request"
    ("checkout API answers with 400 Bad Request", {"400"}),
    ("got a 504 from the load balancer", {"504"}),                   # article between context and code
    ("the gateway returned an 502", {"502"}),
    ("API throwing 500 and 503 intermittently", {"500", "503"}),     # list of codes after one context word
    ("HTTP 502/504 from the edge", {"502", "504"}),
    ("returns 500, 502 or 503 at random", {"500", "502", "503"}),
    ("401 and 403 errors for merchant calls", {"401", "403"}),       # list before an after-context phrase
    # Phase 3: rate limiting described in words is read as 429
    ("partner API keeps saying too many requests", {"429"}),
    ("we are rate limited by the bank gateway", {"429"}),
    ("rate-limiting kicks in on the refunds API", {"429"}),
    ("our calls are being throttled by the acquirer", {"429"}),
    ("HTTP 503 and then throttling from the PSP", {"503", "429"}),
    ("seeing 500s after the deploy", {"500"}),                       # plural code still counts without a duration word
])
def test_http_codes_detected_in_http_context(text, codes):
    assert detect_http_codes(text) == codes


@pytest.mark.parametrize("text", [
    "p99 latency is 500ms",
    "timeout of 500 ms on the gateway",
    "500 transactions failed since morning",
    "failed with 500 transactions pending",
    f"{RUPEE}500 refund failed",
    "refund of 500 rupees failed",
    "port 5432 refused",
    "connect ECONNREFUSED 10.0.3.15:5432",
    "MySQL error 1040: too many connections",
    "response code 05 do not honor",
    "code 91 declines for one issuer",
    "settlement delayed for 400 merchants",
    "disk is at 450 GB",
    "job 503 in the scheduler failed",
    "version 4.03 released yesterday",
    "error rate 5xx above 2%",
    "",
    # Phase 2C.1 negatives: the new article / list handling must not catch quantities
    "processed 400 and 500 records yesterday",   # list without any HTTP context
    "between 400 and 500 users affected",
    "got a 500ms delay on checkout",             # article + duration
    "with a 450 ms spike in latency",
    "returned the 500 records from the archive",  # only "a"/"an" are allowed, not "the"
    "MySQL error 1040 and 1045 in the log",      # 4-digit codes
    "port 5432 or 5433 refused",
    "codes 91 and 05 from the issuer",
    "got an invoice 4031 back",
    # Phase 3 negatives for the rate-limit wording
    "the rate of card declines doubled this morning",
    "error rate above the limit on the dashboard",
    "should we throttle the batch job?",
    # Phase 3: "500s" after a duration word is seconds
    "requests to the gateway fail after a timeout of 500s",
    "the export took 504s to finish",
    "the job failed after 500s",
])
def test_unrelated_numbers_are_not_http_codes(text):
    assert detect_http_codes(text) == set()


def test_entry_code_index_uses_embedded_kb_text():
    assert entry_codes(ENTRIES["KB-006"]) == {"503"}
    assert entry_codes(ENTRIES["KB-002"]) == {"504"}
    assert entry_codes(ENTRIES["KB-004"]) == {"401", "403"}
    assert entry_codes(ENTRIES["KB-001"]) == {"500"} and entry_codes(ENTRIES["KB-003"]) == {"500"}
    assert entry_codes(ENTRIES["KB-005"]) == set()
    assert INDEX.covered == {"401", "403", "500", "503", "504"}


def test_uncovered_codes():
    assert INDEX.uncovered({"429", "503"}) == ["429"]
    assert INDEX.uncovered({"503"}) == []
    assert INDEX.uncovered(set()) == []


def test_code_index_falls_back_to_the_kb_when_retriever_has_no_entries():
    assert CodeIndex.from_retriever(object()).covered == INDEX.covered


def test_rerank_promotes_entry_with_matching_code_and_keeps_score_order():
    ranked = rerank_by_code(results(("KB-005", 0.729), ("KB-002", 0.679), ("KB-006", 0.547)), {"503"}, INDEX, 0.30)
    assert [r.entry.id for r in ranked] == ["KB-006", "KB-005", "KB-002"]


def test_rerank_respects_the_score_floor():
    ranked = rerank_by_code(results(("KB-005", 0.50), ("KB-006", 0.25)), {"503"}, INDEX, 0.30)
    assert [r.entry.id for r in ranked] == ["KB-005", "KB-006"]


def test_rerank_without_codes_changes_nothing():
    original = results(("KB-005", 0.729), ("KB-006", 0.547))
    assert rerank_by_code(original, set(), INDEX, 0.30) == original


def test_rerank_with_two_matching_entries_keeps_their_score_order():
    ranked = rerank_by_code(results(("KB-002", 0.60), ("KB-001", 0.55), ("KB-003", 0.50)), {"500"}, INDEX, 0.30)
    assert [r.entry.id for r in ranked] == ["KB-001", "KB-003", "KB-002"]


def test_rerank_when_no_result_mentions_the_code():
    original = results(("KB-005", 0.70), ("KB-009", 0.40))
    assert [r.entry.id for r in rerank_by_code(original, {"503"}, INDEX, 0.30)] == ["KB-005", "KB-009"]
