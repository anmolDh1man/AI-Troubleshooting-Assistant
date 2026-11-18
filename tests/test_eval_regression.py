"""Regression gate: the full pipeline must not get worse than its recorded baselines.

Baselines come from actual runs (see results/):
  v1  results/eval_summary_after_e04_fix.md  -> 32/33, only E25 fails, 0 confident out-of-KB answers
  v2  results/eval_summary_v2_baseline.md    -> 30/44, 14 known failures, 2 confident out-of-KB answers
      results/eval_summary_v2_phase2a.md     -> 35/44 after the Phase 2A risk-detector redesign
                                                (V37, V38, V40, V41, V42 fixed and locked in below)
      results/eval_summary_v2_phase2b.md     -> 37/44 after Phase 2B input checks
                                                (V35, V36 fixed; confident out-of-KB answers 2 -> 1)
      results/eval_summary_v2_phase2c.md     -> 40/44 after Phase 2C HTTP-code matching
                                                (V20, V21, V23 fixed; Hit@1 23 -> 25; confident out-of-KB 1 -> 0)
  Phase 3 (results/eval_summary_v1_phase3.md, results/eval_summary_v2_phase3.md, results/phase3_dev_probes.md):
      v1 33/33 (E25 fixed by the non-troubleshooting request check)
      v2 43/44 (V02, V03, V07 fixed by error-signature normalisation; Hit@1 25 -> 27)
      Phase 3 dev probes 29/33, then 32/33 after the error-signature re-rank fixed P03, P23 and P31
      (tests/dev_probes_phase3.json, SHA-256 fingerprint below)

A case that starts failing, or more confident out-of-KB answers, fails this test.
Improvements (fewer failures) pass. When a later phase fixes known failures,
shrink the known-failure sets below so the gain is locked in.
"""

import hashlib
import json

import pytest

from src.assistant import INJECTION_MESSAGE, MARKUP_MESSAGE, NON_TROUBLESHOOTING_MESSAGE
from src.config import PROJECT_ROOT
from src.kb_loader import load_knowledge_base
from src.retriever import Retriever
from tests.eval_metrics import false_confident_count, retrieval_summary
from tests.run_eval import build_assistants, run_cases

V1_KNOWN_FAILURES = set()
V1_MAX_FALSE_CONFIDENT = 0
V1_MIN_HIT_AT_1 = 20  # of 20 in-KB cases

V2_KNOWN_FAILURES = {"V13"}
V2_MAX_FALSE_CONFIDENT = 0
V2_MIN_HIT_AT_1 = 27  # of 28 in-KB cases

# Phase 3 development probes (written before the Phase 3 changes; used for development, so not independent).
PROBES_FILE = "dev_probes_phase3.json"
PROBES_SHA256 = "926FCB0486B5AC4C913CEDDC9D16C6341AFEA731DE2AB5FC61F9C91CAB4E76EE"
# P18: the entry that mentions 504 scores 0.2968, below the 0.30 promotion floor, so the answer stays a
# cautious possible match (a fix that raised scores for every status-code query was rejected; see README).
PROBE_KNOWN_FAILURES = {"P18"}


def _cases(name):
    return json.loads((PROJECT_ROOT / "tests" / name).read_text(encoding="utf-8"))["cases"]


@pytest.fixture(scope="module")
def assistants():
    # CHROMA_DIR points at a temporary folder (tests/conftest.py).
    return build_assistants(Retriever(load_knowledge_base()))


@pytest.mark.parametrize("cases_file, known_failures, max_false_confident, min_hit_at_1", [
    ("eval_cases.json", V1_KNOWN_FAILURES, V1_MAX_FALSE_CONFIDENT, V1_MIN_HIT_AT_1),
    ("eval_cases_v2.json", V2_KNOWN_FAILURES, V2_MAX_FALSE_CONFIDENT, V2_MIN_HIT_AT_1),
])
def test_no_regression_against_baseline(assistants, cases_file, known_failures, max_false_confident, min_hit_at_1):
    rows = run_cases(_cases(cases_file), assistants)
    failed = {r["id"] for r in rows if r["result"] == "FAIL"}

    new_failures = {r["id"]: r["failure_reason"] for r in rows if r["id"] in failed - known_failures}
    assert not new_failures, f"New failures in {cases_file}: {new_failures}"
    assert false_confident_count(rows) <= max_false_confident
    assert retrieval_summary(rows, k=3)["hit_at_1"] >= min_hit_at_1


def _probe_failures(probe, response):
    refusal_messages = {INJECTION_MESSAGE, MARKUP_MESSAGE, NON_TROUBLESHOOTING_MESSAGE}
    top = response.sources[0].entry.id if response.sources else None
    failures = []
    if response.status not in probe["allowed_status"]:
        failures.append(f"status {response.status}")
    if probe["expected_top"] and top not in probe["expected_top"]:
        failures.append(f"top {top}")
    if top and top in probe["forbidden_top"]:
        failures.append(f"forbidden top {top}")
    if probe["expect_risk_warning"] is not None and bool(response.risk_warning) != probe["expect_risk_warning"]:
        failures.append(f"risk warning {bool(response.risk_warning)}")
    if probe["expect_refusal"] is not None and (response.message in refusal_messages) != probe["expect_refusal"]:
        failures.append(f"refused {response.message in refusal_messages}")
    return failures


def test_phase3_probes_do_not_regress(assistants):
    path = PROJECT_ROOT / "tests" / PROBES_FILE
    assert hashlib.sha256(path.read_bytes()).hexdigest().upper() == PROBES_SHA256, "probe file was modified"
    probes = json.loads(path.read_text(encoding="utf-8"))["probes"]
    results = {p["id"]: _probe_failures(p, assistants[None].ask(p["query"])) for p in probes}
    new_failures = {pid: f for pid, f in results.items() if f and pid not in PROBE_KNOWN_FAILURES}
    assert not new_failures, f"New probe failures: {new_failures}"
