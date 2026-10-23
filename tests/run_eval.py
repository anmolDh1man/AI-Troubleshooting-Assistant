"""Held-out evaluation of the full pipeline (real KB, real embeddings, real decision logic).

Run from the project root:  python -m tests.run_eval
Writes results/eval_results.csv and results/eval_summary.md

Use --tag to keep an earlier run (e.g. a committed baseline) untouched:
    python -m tests.run_eval --tag after_e04_fix
writes results/eval_results_after_e04_fix.csv and results/eval_summary_after_e04_fix.md
"""

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime

from src.assistant import ANSWERED, LOW_CONFIDENCE, TroubleshootingAssistant
from src.config import PROJECT_ROOT
from src.generator import AnswerGenerator
from src.kb_loader import load_knowledge_base
from src.retriever import Retriever

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

    if case.get("expect_risk_warning") and not response.risk_warning:
        failures.append("missing risky-action warning")

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


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", help="suffix for output files, so earlier results are not overwritten")
    args = parser.parse_args()
    suffix = f"_{args.tag}" if args.tag else ""
    csv_path = RESULTS_DIR / f"eval_results{suffix}.csv"
    summary_path = RESULTS_DIR / f"eval_summary{suffix}.md"

    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]
    retriever = Retriever(load_knowledge_base())
    assistants = {
        None: TroubleshootingAssistant(retriever),
        "broken_generator": TroubleshootingAssistant(retriever, generator=BrokenGenerator()),
        "broken_retriever": TroubleshootingAssistant(BrokenRetriever()),
    }

    rows = []
    for case in cases:
        query = LONG_INPUT if case["query"] == "LONG_INPUT" else case["query"]
        response = assistants[case.get("mode")].ask(query)
        failures = check_case(case, response)
        top = response.sources[0] if response.sources else (response.candidates[0] if response.candidates else None)
        rows.append({
            "id": case["id"],
            "category": case["category"],
            "query": case["query"],
            "expected_status": "|".join(case["expected_status"]),
            "actual_status": response.status,
            "expected_sources": "|".join(case.get("expected_sources") or []) or "-",
            "top_entry": top.entry.id if top else "-",
            "top_score": f"{top.score:.3f}" if top else "-",
            "risk_warning": bool(response.risk_warning),
            "generated_by": response.answer.generated_by if response.answer else "-",
            "result": "PASS" if not failures else "FAIL",
            "failure_reason": "; ".join(failures),
        })

    print(f"{'id':<5}{'category':<25}{'status':<16}{'top':<8}{'score':<7}{'result':<6} query / reason")
    for r in rows:
        print(f"{r['id']:<5}{r['category']:<25}{r['actual_status']:<16}{r['top_entry']:<8}{r['top_score']:<7}{r['result']:<6} "
              f"{r['query'][:55]}" + (f"\n{'':<67}-> {r['failure_reason']}" if r["failure_reason"] else ""))

    by_category = defaultdict(lambda: [0, 0])
    for r in rows:
        by_category[r["category"]][0] += r["result"] == "PASS"
        by_category[r["category"]][1] += 1
    passed = sum(r["result"] == "PASS" for r in rows)

    in_kb = [r for r in rows if r["category"] in ("known_issue", "paraphrase", "paraphrase_hinglish")]
    top1 = sum(r["top_entry"] in r["expected_sources"].split("|") for r in in_kb)
    out_kb = [r for r in rows if r["category"].startswith("unsupported") or r["category"] in ("vague", "prompt_injection")]
    rejected = sum(r["actual_status"] != ANSWERED for r in out_kb)
    confident_wrong = [r for r in out_kb if r["actual_status"] == ANSWERED]

    summary = [
        "# Evaluation summary",
        "",
        f"Run: {datetime.now():%Y-%m-%d %H:%M} · Tag: {args.tag or 'baseline'} · Cases: {len(rows)} · Generator: template (no LLM)",
        "",
        f"**Overall: {passed}/{len(rows)} passed**",
        "",
        f"- Retrieval top-1 accuracy on in-KB queries: {top1}/{len(in_kb)}",
        f"- Out-of-KB / vague queries NOT answered confidently: {rejected}/{len(out_kb)}",
        f"- Confident answers to out-of-KB queries (hallucination risk): {len(confident_wrong)}",
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
