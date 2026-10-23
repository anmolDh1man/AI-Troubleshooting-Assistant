"""Answer generators: turn retrieved KB entries into a structured troubleshooting answer.

The assistant depends only on the AnswerGenerator interface, so an LLM-based
generator (for example a local Ollama model or a hosted API) can be added later
without changing retrieval, decision logic, or the UI.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from src.kb_loader import EscalationRule
from src.retriever import RetrievalResult

SAFETY_NOTE = (
    "This assistant only suggests read-only checks and escalation paths. It does not execute any "
    "action. Steps marked as requiring approval must be performed by an authorised engineer "
    "following the change-management process."
)


@dataclass
class Answer:
    summary: str
    diagnostic_steps: list[str]
    resolution_steps: list[str]
    approval_required: list[str]
    escalation: list[EscalationRule]
    prerequisites: list[str]
    related_ids: list[str]
    cited_ids: list[str]   # KB entries this answer is based on
    generated_by: str      # shown in the UI so users know how the answer was produced


class AnswerGenerator(ABC):
    name: str

    @abstractmethod
    def generate(self, query: str, sources: list[RetrievalResult]) -> Answer:
        """Build an answer using ONLY the given sources (best match first)."""


class TemplateGenerator(AnswerGenerator):
    """Builds the answer directly from the best-matching KB entry, without an LLM.

    Every line is copied from the knowledge base, so it cannot invent a resolution.
    Trade-off: it cannot rephrase or adapt the steps to the user's specific details.
    """

    name = "Knowledge-base template (no LLM)"

    def generate(self, query: str, sources: list[RetrievalResult]) -> Answer:
        if not sources:
            raise ValueError("TemplateGenerator needs at least one source")

        entry = sources[0].entry
        return Answer(
            summary=f"Closest knowledge-base entry: {entry.id}: {entry.title}.",
            diagnostic_steps=list(entry.diagnostic_checks),
            resolution_steps=list(entry.resolution_steps),
            approval_required=list(entry.requires_approval),
            escalation=list(entry.escalation),
            prerequisites=list(entry.prerequisites),
            related_ids=list(entry.related_ids),
            cited_ids=[entry.id],
            generated_by=self.name,
        )


GENERATORS: dict[str, type[AnswerGenerator]] = {
    "template": TemplateGenerator,
    # "ollama": OllamaGenerator,  # possible future addition
}


def get_generator(name: str) -> AnswerGenerator:
    try:
        return GENERATORS[name.strip().lower()]()
    except KeyError:
        raise ValueError(f"Unknown GENERATOR '{name}'. Available: {', '.join(GENERATORS)}") from None
