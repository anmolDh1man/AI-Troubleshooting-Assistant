"""HTTP status-code awareness for ranking and confidence (Phase 2C).

The embedding model treats status codes as near-identical numbers (503 vs 504), so a query that
names a code can be matched to the wrong entry, and a code the knowledge base does not cover at all
(e.g. 429) can still get a confident answer through generic word overlap. This module:

  1. detects HTTP 4xx/5xx codes in a query, only in an HTTP context ("HTTP 503", "returns 500",
     "got a 504", "504s", "400 bad request", "throwing 500 and 503"), never plain numbers
     ("500 transactions", "500ms", "port 5432");
  2. indexes which codes each KB entry mentions in its embedded text (title, symptoms, keywords);
  3. re-ranks the retrieved results so entries mentioning the query's code come first - only
     entries scoring at least the low-confidence floor are promoted;
  4. reports codes that no KB entry mentions, so the assistant never answers them confidently.

Rate-limit wording without a number ("too many requests", "rate limited", "throttled") is read as
HTTP 429 (Phase 3), so it gets the same uncovered-code cap as "HTTP 429".

The knowledge base, embeddings, retrieval and thresholds are unchanged.
"""

import re
from collections.abc import Iterable

from src.kb_loader import KBEntry, load_knowledge_base
from src.retriever import RetrievalResult

_CONTEXT_BEFORE = (r"(?:http|status|code|error|errors|returns?|returning|returned|responds?|responding|response"
                   r"|with|giving|got|getting|throws?|throwing|seeing)")
_CONTEXT_AFTER = (r"(?:errors?|responses?|status|code|bad\s+request|bad\s+gateway|gateway\s+timeout|service\s+unavailable"
                  r"|unauthori[sz]ed|forbidden|not\s+found|too\s+many\s+requests|internal\s+server)")
# A code in context may continue as a list: "throwing 500 and 503", "HTTP 502/504".
_MORE_CODES = r"(?:\s*(?:,|/|&|and|or)\s*[45]\d\d\b)*"
# Units and nouns that show a number is a quantity, not a status code ("with 500 transactions").
_NOT_A_STATUS = (r"(?!\s*(?:ms|%|sec|seconds|mins?|minutes|rupees|rs|inr|usd|merchants|transactions|users))")
_HTTP_CODE = re.compile(
    rf"\b{_CONTEXT_BEFORE}\s*:?\s+(?:an?\s+)?(?P<before>[45]\d\d\b{_MORE_CODES}){_NOT_A_STATUS}"  # "HTTP 503", "got a 504"
    rf"|\b(?P<plural>[45]\d\d)s\b"                                                              # "504s"
    rf"|\b(?P<after>[45]\d\d{_MORE_CODES})\s+{_CONTEXT_AFTER}"                                  # "503 errors"
    rf"|^\s*(?P<alone>[45]\d\d)\s*$",                                                           # just "504"
    re.IGNORECASE,
)
# Rate limiting described in words; "the rate of declines" or "throttle" (an action) do not match.
_RATE_LIMIT = re.compile(r"\btoo\s+many\s+requests\b|\brate[\s-]?limit(?:ed|ing)\b|\bthrottl(?:ed|ing)\b", re.IGNORECASE)
# "500s" right after a duration word means seconds, not "HTTP 500 errors" ("a timeout of 500s", "took 504s").
_DURATION_BEFORE = re.compile(r"(?:timeout(?:\s+of)?|after|took|takes|taking|waited|within|lasted|lasting)\s+$", re.IGNORECASE)
_ANY_CODE = re.compile(r"[45]\d\d")
_KB_CODE = re.compile(r"\b([45]\d\d)\b")


def detect_http_codes(text: str) -> set[str]:
    """HTTP 4xx/5xx status codes mentioned in an HTTP context (including lists such as "500 and 503").

    Rate-limit wording without a number counts as 429.
    """
    text = text or ""
    codes = {code for match in _HTTP_CODE.finditer(text)
             if not (match.group("plural") and _DURATION_BEFORE.search(text[:match.start()]))
             for group in match.groups() if group for code in _ANY_CODE.findall(group)}
    if _RATE_LIMIT.search(text):
        codes.add("429")
    return codes


def entry_codes(entry: KBEntry) -> set[str]:
    """4xx/5xx codes in the text that is embedded for an entry (title, symptoms, keywords)."""
    return {code for _, text in entry.search_chunks() for code in _KB_CODE.findall(text)}


class CodeIndex:
    """Which HTTP codes each KB entry mentions, and which codes the KB covers at all."""

    def __init__(self, entries: Iterable[KBEntry]):
        self.by_entry = {entry.id: entry_codes(entry) for entry in entries}
        self.covered = set().union(*self.by_entry.values()) if self.by_entry else set()

    def uncovered(self, codes: set[str]) -> list[str]:
        return sorted(codes - self.covered)

    @classmethod
    def from_retriever(cls, retriever) -> "CodeIndex":
        entries = getattr(retriever, "entries_by_id", None)
        return cls(entries.values() if entries else load_knowledge_base())


def rerank_by_code(results: list[RetrievalResult], codes: set[str], index: CodeIndex,
                   floor: float) -> list[RetrievalResult]:
    """Move results whose entry mentions one of the query's codes (and scores >= floor) to the front.

    The sort is stable, so score order is kept within each group. Without codes, nothing changes.
    """
    if not codes:
        return results

    def promoted(result: RetrievalResult) -> bool:
        return result.score >= floor and bool(index.by_entry.get(result.entry.id, set()) & codes)

    return sorted(results, key=lambda result: not promoted(result))
