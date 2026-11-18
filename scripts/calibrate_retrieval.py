"""Measure retrieval quality and similarity-score spread to choose a data-driven threshold.

Run from the project root:  python -m scripts.calibrate_retrieval --tag my_run
Writes results/retrieval_calibration_<tag>.csv (without --tag: results/retrieval_calibration.csv).
An existing file is never overwritten unless --overwrite is given, so the committed
calibration record stays intact as historical evidence.
"""

import argparse
import csv
import json

from src.config import PROJECT_ROOT
from src.kb_loader import load_knowledge_base
from src.retriever import Retriever

QUERIES_PATH = PROJECT_ROOT / "scripts" / "calibration_queries.json"
RESULTS_DIR = PROJECT_ROOT / "results"


def main():
    parser = argparse.ArgumentParser(description="Retrieval calibration on the labelled calibration queries")
    parser.add_argument("--tag", help="suffix for the output file, e.g. --tag phase3")
    parser.add_argument("--overwrite", action="store_true", help="allow replacing an existing result file")
    args = parser.parse_args()
    output_path = RESULTS_DIR / (f"retrieval_calibration_{args.tag}.csv" if args.tag else "retrieval_calibration.csv")
    if output_path.exists() and not args.overwrite:
        raise SystemExit(f"Refusing to overwrite {output_path.name}. Use a new --tag (or --overwrite if you really mean it).")

    queries = json.loads(QUERIES_PATH.read_text(encoding="utf-8"))["queries"]
    retriever = Retriever(load_knowledge_base())

    rows = []
    for item in queries:
        results = retriever.search(item["query"], top_k=3)
        top_ids = [r.entry.id for r in results]
        rows.append({
            "type": item["type"],
            "query": item["query"],
            "expected_id": item["expected_id"] or "-",
            "top1_id": top_ids[0],
            "top1_score": results[0].score,
            "top2_id": top_ids[1],
            "top2_score": results[1].score,
            "top1_correct": item["expected_id"] == top_ids[0] if item["expected_id"] else "",
            "in_top3": item["expected_id"] in top_ids if item["expected_id"] else "",
        })

    print(f"{'type':<12}{'top1':<8}{'score':<8}{'2nd':<8}{'score':<8}{'ok':<5}query")
    for row in rows:
        ok = {True: "yes", False: "NO", "": "-"}[row["top1_correct"]]
        print(f"{row['type']:<12}{row['top1_id']:<8}{row['top1_score']:<8}{row['top2_id']:<8}{row['top2_score']:<8}{ok:<5}{row['query']}")

    in_kb = [r for r in rows if r["expected_id"] != "-"]
    out_kb = [r for r in rows if r["expected_id"] == "-"]
    correct_scores = [r["top1_score"] for r in in_kb if r["top1_correct"]]
    out_scores = [r["top1_score"] for r in out_kb]

    print("\nSummary")
    print(f"  Top-1 accuracy (in-KB queries): {sum(r['top1_correct'] for r in in_kb)}/{len(in_kb)}")
    print(f"  Top-3 accuracy (in-KB queries): {sum(r['in_top3'] for r in in_kb)}/{len(in_kb)}")
    print(f"  Lowest score of a correct top-1 match: {min(correct_scores):.3f}")
    print(f"  Highest score of an out-of-KB query:   {max(out_scores):.3f}")
    if min(correct_scores) > max(out_scores):
        print(f"  Scores are separable; a threshold between them works (midpoint {(min(correct_scores) + max(out_scores)) / 2:.3f}).")
    else:
        print("  Scores OVERLAP: no single threshold separates them perfectly; extra checks are needed.")

    RESULTS_DIR.mkdir(exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nSaved: {output_path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
