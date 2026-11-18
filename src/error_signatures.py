"""Error-signature normalisation for retrieval (Phase 3).

The small embedding model splits technical error strings such as EAI_AGAIN, ENOTFOUND or
UnknownHostException into meaningless word pieces, so the rest of the sentence decides the match
(e.g. "EAI_AGAIN when the worker calls the bank API" matched the authentication entry).

This module recognises well-known, documented error strings and appends a plain-language symptom
phrase to the text used for RETRIEVAL ONLY. The user still sees their own text, and HTTP-code
detection and risk checks still read the original query.

It also lists documented error texts that contain action words ("try restarting transaction"), which
the risk check removes so that a pasted error message is not mistaken for a request.
"""

import re

# (signature name, pattern, plain-language symptom phrase appended for retrieval, or None)
# Every signature is also used to re-rank (see rerank_by_signature). Signatures without a phrase are
# re-rank only: plain wording such as "refuses connections" or "connection pool" is common outside
# this domain, so it may reorder the entries whose own text contains it but never raises a score.
_SIGNATURES = [
    ("dns_failure",
     r"\b(?:enotfound|eai_again|eai_noname|getaddrinfo|unknownhostexception|servfail|nxdomain)\b"
     r"|no such host|could not resolve host|temporary failure in name resolution|name or service not known",
     "DNS name resolution failure: unknown host, hostname cannot be resolved"),
    ("connection_refused",
     r"\b(?:econnrefused|connectexception)\b|connection refused",
     "network connection refused: host unreachable, cannot reach the service"),
    ("connection_reset",
     r"\beconnreset\b|connection reset by peer",
     "connection resets between services, network connectivity problem"),
    ("timeout",
     r"\b(?:etimedout|esockettimedout|sockettimeoutexception)\b|read timed out",
     "request timed out: gateway timeout, upstream did not respond in time"),
    ("db_too_many_connections",
     r"too many clients|remaining connection slots are reserved|max_connections|\bora-(?:00020|12519)\b",
     "database too many connections: connection pool exhausted"),
    ("db_lock",
     r"\bdeadlocks?\b|lock wait timeout|\bora-00060\b|could not obtain lock|lock contention",
     "database lock contention: deadlock or long-running query holding locks"),
    # Re-rank only
    ("connection_refused", r"\brefus(?:es|ed|ing)\s+(?:(?:all|new|the|our|any)\s+)?connections?\b", None),
    ("db_connection_pool", r"\bconnection[\s-]pools?\b", None),
]
_COMPILED = [(name, re.compile(pattern, re.IGNORECASE), phrase) for name, pattern, phrase in _SIGNATURES]

# Documented database error texts that contain action words. They describe what happened (or what the
# database itself suggests), not a request by the user, so the risk check ignores them.
_ERROR_MESSAGE_TEXT = re.compile(
    r"\btry\s+restarting\s+transaction\b"                                   # MySQL 1213 / 1205
    r"|\bterminating\s+connection\s+due\s+to\s+administrator\s+command\b"   # PostgreSQL 57P01
    r"|\byour\s+session\s+has\s+been\s+killed\b"                            # ORA-00028
    r"|\bsession\s+marked\s+for\s+kill\b",                                  # ORA-00031
    re.IGNORECASE,
)


def detect_signatures(text: str) -> list[str]:
    """Names of the error signatures found in the text, in definition order (no duplicates)."""
    return list(dict.fromkeys(name for name, pattern, _ in _COMPILED if pattern.search(text or "")))


def expand_for_retrieval(text: str) -> tuple[str, list[str]]:
    """Return (text used for retrieval, signature names). The text is unchanged when no recognised
    signature has a phrase."""
    found = [(name, phrase) for name, pattern, phrase in _COMPILED if pattern.search(text or "")]
    names = list(dict.fromkeys(name for name, _ in found))
    phrases = list(dict.fromkeys(phrase for _, phrase in found if phrase))
    if not phrases:
        return text, names
    return f"{text}. " + ". ".join(phrases), names


# A negated symptom ("the API isn't slow, it ...") pulls retrieval TOWARDS that symptom, because the
# embedding ignores the negation. A curated list of symptom words is removed, with the rest of its
# clause, from the retrieval text when it directly follows a negation.
_NEGATED_SYMPTOM = re.compile(
    r"(?:\bnot|n't|\bnever|\bno\s+longer)\s+(?:(?:really|even|actually|just)\s+)?"
    r"(?:slow|stuck|pending|timing\s+out|timed\s+out|down|unavailable|declined|delayed|full|expired)\b[^,.;]*[,;]?",
    re.IGNORECASE,
)


def drop_negated_symptoms(text: str) -> str:
    """Remove negated symptom clauses ("is not slow", "aren't stuck in pending") from the retrieval text."""
    cleaned = " ".join(_NEGATED_SYMPTOM.sub(" ", text or "").split())
    return cleaned if any(ch.isalpha() for ch in cleaned) else text


class SignatureIndex:
    """Which error signatures appear in each KB entry's own embedded text (title, symptoms, keywords).

    Derived from the KB, not hand-mapped: an entry "has" a signature when the same pattern that
    recognises it in a query also matches the entry's text (e.g. 'connection refused' in KB-007).
    """

    def __init__(self, entries):
        self.by_entry = {entry.id: {name for name, pattern, _ in _COMPILED
                                    if any(pattern.search(text) for _, text in entry.search_chunks())}
                         for entry in entries}

    @classmethod
    def from_retriever(cls, retriever) -> "SignatureIndex":
        from src.kb_loader import load_knowledge_base

        entries = getattr(retriever, "entries_by_id", None)
        return cls(entries.values() if entries else load_knowledge_base())


def rerank_by_signature(results, signatures, index: SignatureIndex, floor: float):
    """Move results whose entry text contains one of the query's error signatures (and scores >= floor)
    to the front, like the HTTP-code re-rank. Stable, so score order is kept within each group."""
    if not signatures:
        return results
    wanted = set(signatures)

    def promoted(result) -> bool:
        return result.score >= floor and bool(index.by_entry.get(result.entry.id, set()) & wanted)

    return sorted(results, key=lambda result: not promoted(result))


def strip_error_messages(text: str) -> str:
    """Remove documented error-message text such as "try restarting transaction" (used before the risk check)."""
    return _ERROR_MESSAGE_TEXT.sub(" ", text or "")
