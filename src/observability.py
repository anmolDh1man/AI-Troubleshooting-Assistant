"""Structured JSON logging (metadata only) and request IDs.

Each log line is one JSON object written to stderr, so it can be collected by Docker, Streamlit Cloud
or any log shipper. Logs never contain the user's query text, credentials or other free text from the
user: request events carry only metadata (status, matched entry, score, zone, latency, safety flags,
query length). Exception messages are scrubbed of the query text before they are logged.
"""

import json
import logging
import sys
import traceback
import uuid
from datetime import UTC, datetime

LOGGER_NAME = "troubleshooting"
# Only these keys may be attached to a log record (logger.info(..., extra={"fields": {...}})).
ALLOWED_FIELDS = frozenset({
    "request_id", "status", "matched_entry", "score", "confidence_zone", "latency_ms", "risk_warning",
    "refusal", "uncovered_codes", "error_type", "error_detail", "query_length", "session_requests",
    "limit", "window_seconds", "check", "ok", "detail", "component", "recovery",
})
_HANDLER_MARK = "_troubleshooting_json_handler"


def new_request_id() -> str:
    """Short random ID shown to the user as a reference and attached to every log line of the request."""
    return uuid.uuid4().hex[:12]


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        fields = getattr(record, "fields", None) or {}
        payload.update({key: value for key, value in fields.items() if key in ALLOWED_FIELDS})
        if record.exc_info and not fields.get("error_detail"):
            # Unscrubbed tracebacks are not logged; callers pass a scrubbed one via safe_error_fields().
            payload["error_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> logging.Logger:
    """Attach one JSON handler to the application logger (idempotent: Streamlit reruns the script)."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    if not any(getattr(handler, _HANDLER_MARK, False) for handler in logger.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(JsonFormatter())
        setattr(handler, _HANDLER_MARK, True)
        logger.addHandler(handler)
    logger.propagate = False
    return logger


def get_logger(component: str) -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{component}")


def safe_error_fields(exc: BaseException, query: str | None = None) -> dict:
    """error_type plus a traceback with the query text (and its stripped form) replaced by [query]."""
    detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    for text in {query, (query or "").strip()} - {None, ""}:
        detail = detail.replace(text, "[query]")
    return {"error_type": type(exc).__name__, "error_detail": detail[-4000:]}
