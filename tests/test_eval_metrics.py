"""Unit tests for evaluation metrics, case checks and the result-file guard (no model needed)."""

import json
import sys
from types import SimpleNamespace

import pytest

import tests.run_eval as run_eval
from src.kb_loader import load_knowledge_base
from src.retriever import RetrievalResult
from tests.eval_metrics import (
    IN_KB, OUT_OF_KB, SPECIAL, case_scope, false_confident_count, hit_at_k, reciprocal_rank,
    retrieval_summary, zone_confusion,
)

ENTRIES = {entry.id: entry for entry in load_knowledge_base()}


def test_hit_at_k():
    ranked = ["KB-002", "KB-001", "KB-005"]
    assert not hit_at_k(ranked, ["KB-001"], 1)
    assert hit_at_k(ranked, ["KB-001"], 2)
    assert not hit_at_k(ranked, ["KB-009"], 3)
    assert hit_at_k(ranked, ["KB-009", "KB-005"], 3)  # any acceptable entry counts


def test_reciprocal_rank():
    ranked = ["KB-002", "KB-001", "KB-005"]
    assert reciprocal_rank(ranked, ["KB-002"], 3) == 1.0
    assert reciprocal_rank(ranked, ["KB-001"], 3) == 0.5
    assert reciprocal_rank(ranked, ["KB-005"], 2) == 0.0  # beyond k
    assert reciprocal_rank([], ["KB-001"], 3) == 0.0


def test_case_scope_explicit_and_inferred():
    assert case_scope({"scope": OUT_OF_KB, "expected_status": ["not_found"]}) == OUT_OF_KB
    assert case_scope({"expected_status": ["answered"], "expected_sources": ["KB-001"]}) == IN_KB
    assert case_scope({"expected_status": ["not_found"], "expected_sources": None}) == OUT_OF_KB
    assert case_scope({"expected_status": ["invalid_input"], "expected_sources": None}) == SPECIAL
    assert case_scope({"expected_status": ["answered"], "expected_sources": ["KB-001"], "mode": "broken_generator"}) == SPECIAL


def _row(scope, status, hit1=False, hitk=False, rr=0.0):
    return {"scope": scope, "actual_status": status, "hit_at_1": hit1, "hit_at_k": hitk, "reciprocal_rank": rr}


def test_retrieval_summary_uses_in_kb_rows_only():
    rows = [_row(IN_KB, "answered", True, True, 1.0), _row(IN_KB, "low_confidence", False, True, 0.5),
            _row(OUT_OF_KB, "not_found"), _row(SPECIAL, "invalid_input")]
    assert retrieval_summary(rows, k=3) == {"n": 2, "hit_at_1": 1, "hit_at_3": 2, "mrr_at_3": 0.75}


def test_zone_confusion_and_false_confident():
    rows = [_row(IN_KB, "answered"), _row(IN_KB, "not_found"), _row(OUT_OF_KB, "answered"),
            _row(OUT_OF_KB, "low_confidence"), _row(OUT_OF_KB, "error"), _row(SPECIAL, "invalid_input")]
    matrix = zone_confusion(rows)
    assert matrix[IN_KB] == {"answered": 1, "low_confidence": 0, "not_found": 1, "other": 0}
    assert matrix[OUT_OF_KB] == {"answered": 1, "low_confidence": 1, "not_found": 0, "other": 1}
    assert false_confident_count(rows) == 1


def _response(status="answered", risk_warning=None):
    entry = ENTRIES["KB-001"]
    source = RetrievalResult(entry, 0.8, entry.title)
    answer = SimpleNamespace(cited_ids=["KB-001"], diagnostic_steps=list(entry.diagnostic_checks),
                             resolution_steps=list(entry.resolution_steps))
    return SimpleNamespace(status=status, sources=[source], candidates=[], answer=answer, risk_warning=risk_warning)


def test_check_case_enforces_expected_absence_of_risk_warning():
    case = {"expected_status": ["answered"], "expected_sources": ["KB-001"], "expect_risk_warning": False}
    assert run_eval.check_case(case, _response(risk_warning=None)) == []
    assert run_eval.check_case(case, _response(risk_warning="careful")) == ["unexpected risky-action warning"]


def test_check_case_flags_invented_steps():
    case = {"expected_status": ["answered"], "expected_sources": ["KB-001"]}
    response = _response()
    response.answer.diagnostic_steps.append("Reboot the mainframe")
    assert any("not found in KB-001" in f for f in run_eval.check_case(case, response))


def test_eval_refuses_to_overwrite_existing_results(tmp_path, monkeypatch):
    (tmp_path / "eval_results_baseline.csv").write_text("existing", encoding="utf-8")
    monkeypatch.setattr(run_eval, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(sys, "argv", ["run_eval", "--tag", "baseline"])
    with pytest.raises(SystemExit, match="Refusing to overwrite"):
        run_eval.main()
    assert (tmp_path / "eval_results_baseline.csv").read_text(encoding="utf-8") == "existing"


def test_calibration_refuses_to_overwrite_existing_results(tmp_path, monkeypatch):
    import scripts.calibrate_retrieval as calibrate

    (tmp_path / "retrieval_calibration.csv").write_text("historical", encoding="utf-8")
    monkeypatch.setattr(calibrate, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(sys, "argv", ["calibrate_retrieval"])
    with pytest.raises(SystemExit, match="Refusing to overwrite"):
        calibrate.main()
    assert (tmp_path / "retrieval_calibration.csv").read_text(encoding="utf-8") == "historical"


def test_v2_cases_are_well_formed_and_new():
    from src.config import PROJECT_ROOT

    v2 = json.loads((PROJECT_ROOT / "tests" / "eval_cases_v2.json").read_text(encoding="utf-8"))["cases"]
    v1 = json.loads((PROJECT_ROOT / "tests" / "eval_cases.json").read_text(encoding="utf-8"))["cases"]
    calib = json.loads((PROJECT_ROOT / "scripts" / "calibration_queries.json").read_text(encoding="utf-8"))["queries"]

    ids = [c["id"] for c in v2]
    assert len(ids) == len(set(ids))
    assert not {c["query"] for c in v2} & ({c["query"] for c in v1} | {q["query"] for q in calib})
    for case in v2:
        assert case["scope"] in (IN_KB, OUT_OF_KB, SPECIAL)
        assert all(s in ENTRIES for s in case.get("expected_sources") or [])
        assert (case["scope"] == IN_KB) == bool(case.get("expected_sources"))
