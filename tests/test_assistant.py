"""Decision-logic tests using a fake retriever with fixed scores (fast, deterministic, no model)."""

import pytest

from src.assistant import (
    ANSWERED, ERROR, INVALID_INPUT, LOW_CONFIDENCE, NOT_FOUND, TroubleshootingAssistant,
)
from src.generator import AnswerGenerator, get_generator
from src.kb_loader import load_knowledge_base
from src.retriever import RetrievalResult

ENTRIES = {entry.id: entry for entry in load_knowledge_base()}


class FakeRetriever:
    """Returns preset (entry_id, score) results and records whether it was called."""

    def __init__(self, scored_ids=(), error=None):
        self.scored_ids = scored_ids
        self.error = error
        self.called = False

    def search(self, query, top_k=3):
        self.called = True
        if self.error:
            raise self.error
        return [RetrievalResult(ENTRIES[i], score, ENTRIES[i].title) for i, score in self.scored_ids][:top_k]


class BrokenGenerator(AnswerGenerator):
    name = "Broken LLM"

    def generate(self, query, sources):
        raise TimeoutError("LLM API timed out")


def make(scored_ids=(), **kwargs):
    retriever = FakeRetriever(scored_ids, kwargs.pop("error", None))
    return TroubleshootingAssistant(retriever, high_threshold=0.45, low_threshold=0.30, **kwargs), retriever


@pytest.mark.parametrize("query", ["", "   ", "a"])
def test_empty_or_tiny_input_is_rejected_without_search(query):
    assistant, retriever = make([("KB-001", 0.9)])
    response = assistant.ask(query)
    assert response.status == INVALID_INPUT
    assert not retriever.called


def test_very_long_input_is_rejected():
    assistant, _ = make([("KB-001", 0.9)])
    assert assistant.ask("error " * 300).status == INVALID_INPUT


def test_high_score_answers_from_the_top_entry_only():
    assistant, _ = make([("KB-001", 0.86), ("KB-002", 0.54)])
    response = assistant.ask("payment api returns 500")
    assert response.status == ANSWERED
    assert response.answer.cited_ids == ["KB-001"]
    assert response.answer.diagnostic_steps == ENTRIES["KB-001"].diagnostic_checks
    assert [r.entry.id for r in response.sources] == ["KB-001"]
    assert [r.entry.id for r in response.candidates] == ["KB-002"]
    assert "no LLM" in response.answer.generated_by


def test_middle_score_is_low_confidence_with_questions():
    assistant, _ = make([("KB-005", 0.41)])
    response = assistant.ask("Kafka consumer lag is increasing")
    assert response.status == LOW_CONFIDENCE
    assert response.answer is not None
    assert response.clarifying_questions


def test_low_score_gives_no_answer_and_no_sources():
    assistant, _ = make([("KB-012", 0.22)])
    response = assistant.ask("the printer is out of paper")
    assert response.status == NOT_FOUND
    assert response.answer is None
    assert response.sources == []
    assert response.clarifying_questions


def test_two_close_high_scores_are_flagged_as_ambiguous():
    assistant, _ = make([("KB-002", 0.775), ("KB-005", 0.733)])
    response = assistant.ask("requests are taking too long")
    assert response.status == ANSWERED
    assert "almost as close" in response.message
    assert ENTRIES["KB-005"].title in response.clarifying_questions[0]


def test_retrieval_failure_returns_error_instead_of_crashing():
    assistant, _ = make(error=RuntimeError("ChromaDB unavailable"))
    response = assistant.ask("payment api returns 500")
    assert response.status == ERROR
    assert response.answer is None


def test_failing_generator_falls_back_to_template():
    assistant, _ = make([("KB-001", 0.86)], generator=BrokenGenerator())
    response = assistant.ask("payment api returns 500")
    assert response.status == ANSWERED
    assert "fallback: Broken LLM failed" in response.answer.generated_by
    assert response.answer.cited_ids == ["KB-001"]


def test_risky_action_query_gets_warning():
    assistant, _ = make([("KB-003", 0.6)])
    response = assistant.ask("should I restart the production database?")
    assert response.risk_warning
    assert any("Restarting" in step for step in response.answer.approval_required)


def test_unknown_generator_name_raises():
    with pytest.raises(ValueError, match="Unknown GENERATOR"):
        get_generator("magic")
