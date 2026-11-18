"""Evaluation metrics (pure functions, no model needed).

Retrieval metrics are computed only on in-KB cases. Each case lists the KB
entries that count as correct ("relevant"). With one relevant entry per case,
Precision@K can never exceed 1/K, so it is not reported; Hit@K (= Recall@K
when there is a single relevant entry) and MRR are used instead.
"""

IN_KB = "in_kb"
OUT_OF_KB = "out_of_kb"
SPECIAL = "special"  # invalid input and simulated failures: no retrieval judgement

ZONE_COLUMNS = ("answered", "low_confidence", "not_found", "other")


def case_scope(case: dict) -> str:
    """Use the case's explicit "scope" if present (v2+), otherwise infer it (v1)."""
    if case.get("scope"):
        return case["scope"]
    if case.get("mode") or case["expected_status"] == ["invalid_input"]:
        return SPECIAL
    return IN_KB if case.get("expected_sources") else OUT_OF_KB


def hit_at_k(ranked_ids: list[str], relevant: list[str], k: int) -> bool:
    return any(entry_id in relevant for entry_id in ranked_ids[:k])


def reciprocal_rank(ranked_ids: list[str], relevant: list[str], k: int) -> float:
    for rank, entry_id in enumerate(ranked_ids[:k], start=1):
        if entry_id in relevant:
            return 1 / rank
    return 0.0


def retrieval_summary(rows: list[dict], k: int) -> dict:
    """Hit@1, Hit@k and MRR@k over rows with scope in_kb."""
    in_kb = [r for r in rows if r["scope"] == IN_KB]
    n = len(in_kb)
    return {
        "n": n,
        "hit_at_1": sum(r["hit_at_1"] for r in in_kb),
        f"hit_at_{k}": sum(r["hit_at_k"] for r in in_kb),
        f"mrr_at_{k}": round(sum(r["reciprocal_rank"] for r in in_kb) / n, 3) if n else 0.0,
    }


def zone_confusion(rows: list[dict]) -> dict:
    """Counts of actual status per scope, e.g. {"in_kb": {"answered": 14, ...}, "out_of_kb": {...}}."""
    matrix = {scope: dict.fromkeys(ZONE_COLUMNS, 0) for scope in (IN_KB, OUT_OF_KB)}
    for r in rows:
        if r["scope"] in matrix:
            column = r["actual_status"] if r["actual_status"] in ZONE_COLUMNS else "other"
            matrix[r["scope"]][column] += 1
    return matrix


def false_confident_count(rows: list[dict]) -> int:
    """Out-of-KB cases that received a confident answer: the hallucination-risk number."""
    return sum(r["scope"] == OUT_OF_KB and r["actual_status"] == "answered" for r in rows)
