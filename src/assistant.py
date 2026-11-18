"""Orchestrates one troubleshooting request: validate input -> retrieve -> decide -> generate.

Run from the project root for a quick terminal check:
    python -m src.assistant "The payment API is returning a 500 error"
"""

import sys
import time
from dataclasses import dataclass, field

from src.code_matching import CodeIndex, detect_http_codes, rerank_by_code
from src.config import GENERATOR, HIGH_CONFIDENCE_THRESHOLD, LOW_CONFIDENCE_THRESHOLD, TOP_K
from src.error_signatures import SignatureIndex, drop_negated_symptoms, expand_for_retrieval, rerank_by_signature
from src.generator import SAFETY_NOTE, Answer, AnswerGenerator, TemplateGenerator, get_generator
from src.guardrails import assess_risk, risk_warning_text
from src.input_checks import INJECTION, MARKUP_ONLY, NON_TROUBLESHOOTING, check_input
from src.observability import get_logger, new_request_id, safe_error_fields
from src.retriever import IndexUnavailableError, RetrievalResult

logger = get_logger("assistant")

MIN_QUERY_CHARS = 3
MAX_QUERY_CHARS = 1000
MAX_RAW_CHARS = 20 * MAX_QUERY_CHARS  # huge pastes are refused before any processing
AMBIGUITY_MARGIN = 0.05  # two entries this close in score are both shown as candidates
CODE_POOL_K = 5  # results considered for the HTTP-code re-rank (only top_k are kept)

TOO_LONG_MESSAGE = (f"Please shorten the description to under {MAX_QUERY_CHARS} characters "
                    "(paste only the key error lines, not full logs).")
INJECTION_MESSAGE = ("This assistant only answers troubleshooting questions from its knowledge base. It has no admin "
                     "mode, hidden instructions or secrets to reveal, so this request was not processed. Please "
                     "describe the technical issue you are seeing.")
MARKUP_MESSAGE = ("This looks like code or markup rather than a description of a problem, so it was not searched. "
                  "Please describe the issue in words: the error message, the affected service, and when it started.")
NON_TROUBLESHOOTING_MESSAGE = ("This assistant only helps with troubleshooting technical issues from its knowledge base, so it "
                               "cannot write stories, poems or jokes or translate text. Please describe the technical issue "
                               "you are seeing.")
# Error messages never contain exception text; the reference ID links them to the internal log line.
SEARCH_FAILED_MESSAGE = ("The knowledge-base search failed. Please try again; if it keeps failing, report reference ID "
                         "{request_id} to the application owner.")
INDEX_UNAVAILABLE_MESSAGE = ("The knowledge-base index is not available right now, so no search was done. Please try again "
                             "in a minute; if it keeps failing, report reference ID {request_id} to the application owner.")
GENERATION_FAILED_MESSAGE = ("The answer could not be generated (reference ID {request_id}). The matching entry is "
                             "listed below.")
UNEXPECTED_ERROR_MESSAGE = ("Something went wrong while handling this request. Please try again; if it keeps failing, "
                            "report reference ID {request_id} to the application owner.")

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
    request_id: str = ""            # shown as the reference ID on errors; also in the log line
    refusal: str | None = None      # injection / markup_only / non_troubleshooting when the input was refused
    error_type: str | None = None   # exception class name for ERROR responses (never shown to the user)
    uncovered_codes: list[str] = field(default_factory=list)


class TroubleshootingAssistant:
    def __init__(
        self,
        retriever,
        generator: AnswerGenerator | None = None,
        high_threshold: float = HIGH_CONFIDENCE_THRESHOLD,
        low_threshold: float = LOW_CONFIDENCE_THRESHOLD,
        top_k: int = TOP_K,
        code_index: CodeIndex | None = None,
    ):
        self.retriever = retriever
        self.generator = generator or TemplateGenerator()
        self.high_threshold = high_threshold
        self.low_threshold = low_threshold
        self.top_k = top_k
        self.code_index = code_index or CodeIndex.from_retriever(retriever)
        self.signature_index = SignatureIndex.from_retriever(retriever)

    def ask(self, raw_query: str) -> AssistantResponse:
        """Handle one request: never raises, and writes one metadata-only log line (no query text)."""
        request_id = new_request_id()
        started = time.perf_counter()
        try:
            response = self._decide(raw_query, request_id)
        except Exception as exc:  # last line of defence: the user sees a reference ID, never the exception
            logger.error("unexpected error", extra={"fields": {"request_id": request_id, **safe_error_fields(exc, raw_query)}})
            response = AssistantResponse(ERROR, UNEXPECTED_ERROR_MESSAGE.format(request_id=request_id),
                                         (raw_query or "")[:MAX_QUERY_CHARS], error_type=type(exc).__name__)
        response.request_id = request_id
        self._log_request(response, len(raw_query or ""), (time.perf_counter() - started) * 1000)
        return response

    def _log_request(self, response: AssistantResponse, query_length: int, latency_ms: float) -> None:
        top = response.sources[0] if response.sources else None
        logger.info("request", extra={"fields": {
            "request_id": response.request_id,
            "status": response.status,
            "matched_entry": top.entry.id if top else None,
            "score": top.score if top else None,
            "confidence_zone": (response.status if response.status in (ANSWERED, LOW_CONFIDENCE, NOT_FOUND)
                                else None) if response.refusal is None else "refused",
            "latency_ms": round(latency_ms, 1),
            "risk_warning": bool(response.risk_warning),
            "refusal": response.refusal,
            "uncovered_codes": response.uncovered_codes or None,
            "error_type": response.error_type,
            "query_length": query_length,
        }})

    def _decide(self, raw_query: str, request_id: str) -> AssistantResponse:
        if len(raw_query or "") > MAX_RAW_CHARS:
            return AssistantResponse(INVALID_INPUT, TOO_LONG_MESSAGE, (raw_query or "")[:MAX_QUERY_CHARS])

        # Normalize and classify before anything else: suspicious input never reaches retrieval.
        checked = check_input(raw_query)
        query = checked.text
        if checked.kind == INJECTION:
            return AssistantResponse(NOT_FOUND, INJECTION_MESSAGE, query, refusal=INJECTION)
        if checked.kind == MARKUP_ONLY:
            return AssistantResponse(NOT_FOUND, MARKUP_MESSAGE, query, clarifying_questions=CLARIFYING_QUESTIONS,
                                     refusal=MARKUP_ONLY)
        if checked.kind == NON_TROUBLESHOOTING:
            return AssistantResponse(NOT_FOUND, NON_TROUBLESHOOTING_MESSAGE, query, refusal=NON_TROUBLESHOOTING)

        if len(query) < MIN_QUERY_CHARS:
            return AssistantResponse(INVALID_INPUT, "Please describe the issue you are seeing.", query,
                                     clarifying_questions=CLARIFYING_QUESTIONS)
        if len(query) > MAX_QUERY_CHARS:
            return AssistantResponse(INVALID_INPUT, TOO_LONG_MESSAGE, query[:MAX_QUERY_CHARS])

        risk_warning = risk_warning_text(assess_risk(query))

        # Well-known error strings (EAI_AGAIN, UnknownHostException, ...) get a plain-language symptom
        # phrase appended for retrieval only; the user's own text is used everywhere else.
        # Negated symptoms ("isn't slow") are dropped from the retrieval text for the same reason.
        search_text, signatures = expand_for_retrieval(drop_negated_symptoms(query))
        codes = detect_http_codes(query)
        try:
            # With a status code or error signature, a wider pool lets an entry that mentions it (ranked 4th
            # or 5th by similarity) be promoted; only the first top_k results are kept and shown.
            pool = max(self.top_k, CODE_POOL_K) if codes or signatures else self.top_k
            results = self.retriever.search(search_text, top_k=pool)
        except IndexUnavailableError as exc:
            logger.error("vector index unavailable", extra={"fields": {"request_id": request_id, **safe_error_fields(exc, query)}})
            return AssistantResponse(ERROR, INDEX_UNAVAILABLE_MESSAGE.format(request_id=request_id), query,
                                     risk_warning=risk_warning, error_type=type(exc).__name__)
        except Exception as exc:
            logger.error("retrieval failed", extra={"fields": {"request_id": request_id, **safe_error_fields(exc, query)}})
            return AssistantResponse(ERROR, SEARCH_FAILED_MESSAGE.format(request_id=request_id), query,
                                     risk_warning=risk_warning, error_type=type(exc).__name__)

        # An exact error signature or HTTP status code outranks general similarity: entries whose own text
        # contains it move to the front (only those at or above the low-confidence floor). The code
        # re-rank runs last, so a status code takes precedence over an error signature.
        results = rerank_by_signature(results, signatures, self.signature_index, self.low_threshold)
        results = rerank_by_code(results, codes, self.code_index, self.low_threshold)[:self.top_k]
        uncovered = self.code_index.uncovered(codes)

        if not results or results[0].score < self.low_threshold:
            return AssistantResponse(
                NOT_FOUND,
                "The knowledge base does not contain a matching entry for this issue, so no resolution is suggested. "
                "Please add more details, or escalate to L2 Application Support if the issue is urgent.",
                query, candidates=results, clarifying_questions=CLARIFYING_QUESTIONS, risk_warning=risk_warning,
            )

        top, others = results[0], results[1:]
        answer = self._generate(query, [top], request_id)
        if answer is None:
            return AssistantResponse(ERROR, GENERATION_FAILED_MESSAGE.format(request_id=request_id), query,
                                     sources=[top], candidates=others, risk_warning=risk_warning,
                                     error_type="GenerationError")

        # A status code that no KB entry covers is never answered confidently, however high the score.
        if top.score < self.high_threshold or uncovered:
            if uncovered:
                message = (f"The knowledge base has no entry for HTTP {', '.join(uncovered)}, so this is only the closest "
                           f"related entry (similarity {top.score:.2f}), not a confirmed match. Verify that the "
                           "symptoms below match your issue before following these steps.")
            else:
                message = (f"Possible match only (similarity {top.score:.2f}). Verify that the symptoms below match "
                           "your issue before following these steps, and share more details for a better match.")
            # Near tie in this zone too (text only; the status and the entry used do not change).
            near = [r for r in others if r.score >= self.low_threshold and abs(top.score - r.score) <= AMBIGUITY_MARGIN]
            if near:
                message += f" {near[0].entry.id} ({near[0].entry.title}) is almost as close; compare the symptoms of both."
            return AssistantResponse(LOW_CONFIDENCE, message, query, answer, [top], others, CLARIFYING_QUESTIONS,
                                     risk_warning, uncovered_codes=uncovered)

        # abs(): after a code re-rank, another entry can score higher than the top one; that is not "almost as close".
        close = [r for r in others if r.score >= self.high_threshold and abs(top.score - r.score) <= AMBIGUITY_MARGIN]
        message = f"Matched {top.entry.id} with high similarity ({top.score:.2f})."
        questions = []
        if close:
            message += " Another entry is almost as close; compare the symptoms of both."
            questions = [f"Which describes your issue better: '{top.entry.title}' or '{close[0].entry.title}'?"]
        return AssistantResponse(ANSWERED, message, query, answer, [top], others, questions, risk_warning)

    def _generate(self, query: str, sources: list[RetrievalResult], request_id: str = "") -> Answer | None:
        """Run the configured generator; if a non-template generator fails, fall back to the template."""
        try:
            return self.generator.generate(query, sources)
        except Exception as exc:
            logger.error("generator failed", extra={"fields": {"request_id": request_id, "component": self.generator.name,
                                                               **safe_error_fields(exc, query)}})
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
