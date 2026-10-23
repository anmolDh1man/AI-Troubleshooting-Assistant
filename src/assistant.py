"""Orchestrates one troubleshooting request: validate input -> retrieve -> decide -> generate.

Run from the project root for a quick terminal check:
    python -m src.assistant "The payment API is returning a 500 error"
"""

import logging
import re
import sys
from dataclasses import dataclass, field

from src.config import GENERATOR, HIGH_CONFIDENCE_THRESHOLD, LOW_CONFIDENCE_THRESHOLD, TOP_K
from src.generator import SAFETY_NOTE, Answer, AnswerGenerator, TemplateGenerator, get_generator
from src.retriever import RetrievalResult

logger = logging.getLogger(__name__)

MIN_QUERY_CHARS = 3
MAX_QUERY_CHARS = 1000
AMBIGUITY_MARGIN = 0.05  # two entries this close in score are both shown as candidates

RISKY_ACTION_PATTERN = re.compile(
    r"\b(restart|reboot|kill|delete|drop|truncate|roll ?back|revert|purge|wipe|shut ?down|"
    r"reprocess|refund|force[- ]approve|disable)\w*",
    re.IGNORECASE,
)

# Response statuses
ANSWERED = "answered"
LOW_CONFIDENCE = "low_confidence"
NOT_FOUND = "not_found"
INVALID_INPUT = "invalid_input"
ERROR = "error"

CLARIFYING_QUESTIONS = [
    "Which service, API, or component is affected?",
    "What exact error message or HTTP status code do you see?",
    "When did the issue start, and was there any recent deployment or change?",
    "How many users, merchants, or transactions are affected?",
]


@dataclass
class AssistantResponse:
    status: str
    message: str
    query: str
    answer: Answer | None = None
    sources: list[RetrievalResult] = field(default_factory=list)       # entries the answer is based on
    candidates: list[RetrievalResult] = field(default_factory=list)    # other retrieved entries, NOT used
    clarifying_questions: list[str] = field(default_factory=list)
    risk_warning: str | None = None
    safety_note: str = SAFETY_NOTE


class TroubleshootingAssistant:
    def __init__(
        self,
        retriever,
        generator: AnswerGenerator | None = None,
        high_threshold: float = HIGH_CONFIDENCE_THRESHOLD,
        low_threshold: float = LOW_CONFIDENCE_THRESHOLD,
        top_k: int = TOP_K,
    ):
        self.retriever = retriever
        self.generator = generator or TemplateGenerator()
        self.high_threshold = high_threshold
        self.low_threshold = low_threshold
        self.top_k = top_k

    def ask(self, raw_query: str) -> AssistantResponse:
        query = " ".join((raw_query or "").split())  # trim + collapse whitespace

        if len(query) < MIN_QUERY_CHARS:
            return AssistantResponse(INVALID_INPUT, "Please describe the issue you are seeing.", query,
                                     clarifying_questions=CLARIFYING_QUESTIONS)
        if len(query) > MAX_QUERY_CHARS:
            return AssistantResponse(INVALID_INPUT, f"Please shorten the description to under {MAX_QUERY_CHARS} characters "
                                     "(paste only the key error lines, not full logs).", query[:MAX_QUERY_CHARS])

        risk_warning = None
        if RISKY_ACTION_PATTERN.search(query):
            risk_warning = ("Your question mentions a potentially disruptive action. Do not perform it on production "
                            "without approval; check the 'Requires approval' section and escalate.")

        try:
            results = self.retriever.search(query, top_k=self.top_k)
        except Exception:
            logger.exception("Retrieval failed")
            return AssistantResponse(ERROR, "The knowledge-base search failed. Please try again; if it keeps failing, "
                                     "check the application logs.", query, risk_warning=risk_warning)

        if not results or results[0].score < self.low_threshold:
            return AssistantResponse(
                NOT_FOUND,
                "The knowledge base does not contain a matching entry for this issue, so no resolution is suggested. "
                "Please add more details, or escalate to L2 Application Support if the issue is urgent.",
                query, candidates=results, clarifying_questions=CLARIFYING_QUESTIONS, risk_warning=risk_warning,
            )

        top, others = results[0], results[1:]
        answer = self._generate(query, [top])
        if answer is None:
            return AssistantResponse(ERROR, "The answer could not be generated. The matching entry is listed below.",
                                     query, sources=[top], candidates=others, risk_warning=risk_warning)

        if top.score < self.high_threshold:
            return AssistantResponse(
                LOW_CONFIDENCE,
                f"Possible match only (similarity {top.score:.2f}). Verify that the symptoms below match your issue "
                "before following these steps, and share more details for a better match.",
                query, answer, [top], others, CLARIFYING_QUESTIONS, risk_warning,
            )

        close = [r for r in others if r.score >= self.high_threshold and top.score - r.score <= AMBIGUITY_MARGIN]
        message = f"Matched {top.entry.id} with high similarity ({top.score:.2f})."
        questions = []
        if close:
            message += " Another entry is almost as close; compare the symptoms of both."
            questions = [f"Which describes your issue better: '{top.entry.title}' or '{close[0].entry.title}'?"]
        return AssistantResponse(ANSWERED, message, query, answer, [top], others, questions, risk_warning)

    def _generate(self, query: str, sources: list[RetrievalResult]) -> Answer | None:
        """Run the configured generator; if a non-template generator fails, fall back to the template."""
        try:
            return self.generator.generate(query, sources)
        except Exception:
            logger.exception("Generator '%s' failed", self.generator.name)
            if isinstance(self.generator, TemplateGenerator):
                return None
            answer = TemplateGenerator().generate(query, sources)
            answer.generated_by += f" (fallback: {self.generator.name} failed)"
            return answer


def build_assistant() -> TroubleshootingAssistant:
    """Create the assistant with the real KB, retriever, and configured generator."""
    from src.kb_loader import load_knowledge_base
    from src.retriever import Retriever

    return TroubleshootingAssistant(Retriever(load_knowledge_base()), get_generator(GENERATOR))


def format_response(response: AssistantResponse) -> str:
    """Plain-text rendering for the terminal (the Streamlit UI has its own rendering)."""
    lines = [f"[{response.status.upper()}] {response.message}"]
    if response.risk_warning:
        lines.append(f"WARNING: {response.risk_warning}")
    if response.answer:
        a = response.answer
        lines += ["", a.summary, "", "Diagnostic checks:"]
        lines += [f"  {i}. {step}" for i, step in enumerate(a.diagnostic_steps, 1)]
        lines += ["", "Known resolution / safe next steps:"] + [f"  - {s}" for s in a.resolution_steps]
        if a.approval_required:
            lines += ["", "Requires approval (do NOT do without authorisation):"] + [f"  ! {s}" for s in a.approval_required]
        lines += ["", "Escalation:"] + [f"  -> {rule.team}: {rule.when}" for rule in a.escalation]
        lines += ["", f"Generated by: {a.generated_by}"]
    if response.sources:
        lines += ["", "Sources used:"]
        lines += [f"  {r.entry.id} (similarity {r.score:.2f}) matched: \"{r.matched_text}\"" for r in response.sources]
    if response.candidates:
        lines += ["", "Other retrieved entries (not used):"]
        lines += [f"  {r.entry.id} {r.entry.title} ({r.score:.2f})" for r in response.candidates]
    if response.clarifying_questions:
        lines += ["", "To help further, please answer:"] + [f"  ? {q}" for q in response.clarifying_questions]
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python -m src.assistant "describe the issue"')
        sys.exit(1)
    print(format_response(build_assistant().ask(" ".join(sys.argv[1:]))))
