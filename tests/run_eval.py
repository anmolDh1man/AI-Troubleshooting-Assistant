"""End-to-end evaluation of the full pipeline (real KB, real embeddings, real decision logic).

Run from the project root:
    python -m tests.run_eval --tag my_run                                   # v1 cases (tests/eval_cases.json)
    python -m tests.run_eval --cases tests/eval_cases_v2.json --tag v2_run  # v2 cases

Writes results/eval_results_<tag>.csv and results/eval_summary_<tag>.md.
Existing result files are never overwritten unless --overwrite is given, so
committed baselines (e.g. eval_results.csv, eval_results_after_e04_fix.csv)
stay intact as historical evidence.
"""

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from src.assistant import ANSWERED, LOW_CONFIDENCE, TroubleshootingAssistant
from src.config import PROJECT_ROOT, TOP_K
from src.generator import AnswerGenerator
from src.kb_loader import load_knowledge_base
from src.retriever import Retriever
from tests.eval_metrics import (
    IN_KB, OUT_OF_KB, ZONE_COLUMNS, case_scope, false_confident_count, hit_at_k, reciprocal_rank,
    retrieval_summary, zone_confusion,
)

CASES_PATH = PROJECT_ROOT / "tests" / "eval_cases.json"
RESULTS_DIR = PROJECT_ROOT / "results"
LONG_INPUT = "Payment API error with stack trace. " * 50  # ~1,800 characters


class BrokenGenerator(AnswerGenerator):
    """Simulates an LLM provider outage (timeout)."""
    name = "Simulated LLM"

    def generate(self, query, sources):
        raise TimeoutError("simulated LLM timeout")


class BrokenRetriever:
    """Simulates the vector store being unavailable."""

    def search(self, query, top_k=3):
        raise ConnectionError("simulated vector store outage")


def check_case(case: dict, response) -> list[str]:
    """Return the list of failed checks for one case (empty list = PASS)."""
    failures = []
    source_ids = [r.entry.id for r in response.sources]

    if response.status not in case["expected_status"]:
        failures.append(f"status={response.status}, expected {case['expected_status']}")

    expected_sources = case.get("expected_sources")
    if expected_sources:
        if response.status in (ANSWERED, LOW_CONFIDENCE) and (not source_ids or source_ids[0] not in expected_sources):
            failures.append(f"source={source_ids or None}, expected one of {expected_sources}")
    elif response.status == ANSWERED:
        failures.append("gave a confident answer for an issue that is not in the KB")

    if case.get("expect_risk_warning") is True and not response.risk_warning:
        failures.append("missing risky-action warning")
    if case.get("expect_risk_warning") is False and response.risk_warning:
        failures.append("unexpected risky-action warning")

    if response.answer:
        # Attribution: the answer must cite exactly the sources shown to the user.
        if response.answer.cited_ids != source_ids:
            failures.append(f"cited {response.answer.cited_ids} but displayed {source_ids}")
        # Grounding: every step must come from the cited entry (no invented steps).
        cited = response.sources[0].entry
        kb_text = cited.diagnostic_checks + cited.resolution_steps
        invented = [s for s in response.answer.diagnostic_steps + response.answer.resolution_steps if s not in kb_text]
        if invented:
            failures.append(f"{len(invented)} step(s) not found in {cited.id}")

    if response.status not in (ANSWERED, LOW_CONFIDENCE) and response.answer is not None:
        failures.append("returned an answer despite a non-answer status")

    return failures


def build_assistants(retriever) -> dict:
    return {
        None: TroubleshootingAssistant(retriever),
        "broken_generator": TroubleshootingAssistant(retriever, generator=BrokenGenerator()),
        "broken_retriever": TroubleshootingAssistant(BrokenRetriever()),
    }


def run_cases(cases: list[dict], assistants: dict, k: int = TOP_K) -> list[dict]:
    """Run every case and return one result row per case (including retrieval metrics)."""
    rows = []
    for case in cases:
        query = LONG_INPUT if case["query"] == "LONG_INPUT" else case["query"]
        response = assistants[case.get("mode")].ask(query)
        failures = check_case(case, response)
        ranked = response.sources + response.candidates
        ranked_ids = [r.entry.id for r in ranked]
        relevant = case.get("expected_sources") or []
        top = ranked[0] if ranked else None
        rows.append({
            "id": case["id"],
            "category": case["category"],
            "scope": case_scope(case),
            "query": case["query"],
            "expected_status": "|".join(case["expected_status"]),
            "actual_status": response.status,
            "expected_sources": "|".join(relevant) or "-",
            "top_entry": top.entry.id if top else "-",
            "top_score": f"{top.score:.3f}" if top else "-",
            "ranked_ids": "|".join(ranked_ids) or "-",
            "hit_at_1": hit_at_k(ranked_ids, relevant, 1),
            "hit_at_k": hit_at_k(ranked_ids, relevant, k),
            "reciprocal_rank": round(reciprocal_rank(ranked_ids, relevant, k), 3),
            "risk_warning": bool(response.risk_warning),
            "generated_by": response.answer.generated_by if response.answer else "-",
            "result": "PASS" if not failures else "FAIL",
            "failure_reason": "; ".join(failures),
        })
    return rows


def summarize(rows: list[dict], cases_name: str, tag: str, k: int = TOP_K) -> list[str]:
    """Markdown summary: pass rate, retrieval metrics, zone confusion matrix, failures."""
    by_category = defaultdict(lambda: [0, 0])
    for r in rows:
        by_category[r["category"]][0] += r["result"] == "PASS"
        by_category[r["category"]][1] += 1
    passed = sum(r["result"] == "PASS" for r in rows)
    retrieval = retrieval_summary(rows, k)
    matrix = zone_confusion(rows)
    out_kb_total = sum(matrix[OUT_OF_KB].values())

    return [
        "# Evaluation summary",
        "",
        f"Run: {datetime.now():%Y-%m-%d %H:%M} · Cases: `{cases_name}` ({len(rows)}) · Tag: {tag} · Generator: template (no LLM)",
        "",
        f"**Overall: {passed}/{len(rows)} passed**",
        "",
        f"## Retrieval (in-KB cases, k={k})",
        "",
        f"- Hit@1: {retrieval['hit_at_1']}/{retrieval['n']}",
        f"- Hit@{k}: {retrieval[f'hit_at_{k}']}/{retrieval['n']}",
        f"- MRR@{k}: {retrieval[f'mrr_at_{k}']}",
        "",
        "## Decision zones (actual status by scope)",
        "",
        "| Scope | " + " | ".join(ZONE_COLUMNS) + " |",
        "|---|" + "---|" * len(ZONE_COLUMNS),
        *[f"| {scope} | " + " | ".join(str(matrix[scope][c]) for c in ZONE_COLUMNS) + " |" for scope in (IN_KB, OUT_OF_KB)],
        "",
        f"- Confident answers to out-of-KB queries (hallucination risk): {false_confident_count(rows)}/{out_kb_total}",
        "",
        "## Pass rate by category",
        "",
        "| Category | Passed |",
        "|---|---|",
        *[f"| {cat} | {p}/{t} |" for cat, (p, t) in by_category.items()],
        "",
        "## Failures",
        "",
        *([f"- **{r['id']}** ({r['category']}) `{r['query'][:70]}`: {r['failure_reason']}" for r in rows if r["result"] == "FAIL"]
          or ["None."]),
    ]


def main():
    parser = argparse.ArgumentParser(description="End-to-end evaluation of the troubleshooting assistant")
    parser.add_argument("--cases", default=str(CASES_PATH), help="evaluation cases JSON (default: v1 tests/eval_cases.json)")
    parser.add_argument("--tag", help="suffix for output files, e.g. --tag v2_baseline")
    parser.add_argument("--overwrite", action="store_true", help="allow replacing existing result files")
    args = parser.parse_args()

    suffix = f"_{args.tag}" if args.tag else ""
    csv_path = RESULTS_DIR / f"eval_results{suffix}.csv"
    summary_path = RESULTS_DIR / f"eval_summary{suffix}.md"
    existing = [p for p in (csv_path, summary_path) if p.exists()]
    if existing and not args.overwrite:
        raise SystemExit(f"Refusing to overwrite {', '.join(p.name for p in existing)}. "
                         "Use a new --tag (or --overwrite if you really mean it).")

    cases_path = Path(args.cases)
    cases = json.loads(cases_path.read_text(encoding="utf-8"))["cases"]
    rows = run_cases(cases, build_assistants(Retriever(load_knowledge_base())))

    print(f"{'id':<5}{'scope':<10}{'status':<16}{'top':<8}{'score':<7}{'result':<6} query / reason")
    for r in rows:
        print(f"{r['id']:<5}{r['scope']:<10}{r['actual_status']:<16}{r['top_entry']:<8}{r['top_score']:<7}{r['result']:<6} "
              f"{r['query'][:55]}" + (f"\n{'':<52}-> {r['failure_reason']}" if r["failure_reason"] else ""))

    summary = summarize(rows, cases_path.name, args.tag or "untagged")
    print("\n" + "\n".join(summary))

    RESULTS_DIR.mkdir(exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    summary_path.write_text("\n".join(summary) + "\n", encoding="utf-8")
    print(f"\nSaved: {csv_path.relative_to(PROJECT_ROOT)}, {summary_path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
