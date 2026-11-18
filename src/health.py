"""Application health checks: configuration, knowledge base, embedding model, vector index, match indexes.

Used by app.py at startup (the app refuses to serve if a check fails) and in the sidebar, and by
operators from the command line:
    python -m src.health            # prints one JSON line per check; exit code 1 if any check fails
The checks use a fixed probe sentence, never user input. Details contain counts and names only.
"""

import json
import sys
from dataclasses import asdict, dataclass

from src.config import ConfigError, load_settings
from src.kb_loader import KBValidationError, load_knowledge_base
from src.observability import get_logger

logger = get_logger("health")
PROBE_TEXT = "health check: payment API returns HTTP 500"


@dataclass(frozen=True)
class HealthCheck:
    name: str
    ok: bool
    detail: str


def _check(name: str, func) -> HealthCheck:
    try:
        ok, detail = func()
    except Exception as exc:  # a failing check reports its exception type only
        ok, detail = False, f"{type(exc).__name__} while checking"
    if not ok:
        logger.error("health check failed", extra={"fields": {"check": name, "ok": False, "detail": detail}})
    return HealthCheck(name, ok, detail)


def run_health_checks(assistant) -> list[HealthCheck]:
    retriever = assistant.retriever
    kb_ids = set(getattr(retriever, "entries_by_id", {}))

    def configuration():
        try:
            settings = load_settings()
        except ConfigError as exc:
            return False, str(exc)
        return True, (f"thresholds {settings.low_confidence_threshold:.2f}/{settings.high_confidence_threshold:.2f}, "
                      f"top_k {settings.top_k}, generator {settings.generator}")

    def knowledge_base():
        try:
            entries = load_knowledge_base()
        except KBValidationError as exc:
            return False, str(exc).splitlines()[0]
        loaded = {entry.id for entry in entries}
        if loaded != kb_ids:
            return False, f"{len(loaded)} valid entries on disk, but {len(kb_ids)} loaded in the running app (restart needed)"
        return True, f"{len(entries)} valid entries"

    def embedding_model():
        vector = retriever.model.encode([PROBE_TEXT], normalize_embeddings=True)
        dims = len(vector[0])
        revision = retriever.model_revision or "latest"
        return dims > 0, f"{retriever.model_name} (revision {revision[:12]}), {dims} dimensions"

    def vector_index():
        count = retriever.collection.count()
        if not retriever.is_consistent():
            return False, f"{count} chunks indexed, {retriever.expected_chunks} expected, or the KB/model fingerprint differs"
        return True, f"{count} chunks indexed, fingerprint matches"

    def match_indexes():
        missing = kb_ids - set(assistant.code_index.by_entry) | kb_ids - set(assistant.signature_index.by_entry)
        if missing:
            return False, f"entries missing from the code/signature index: {', '.join(sorted(missing))}"
        return True, (f"HTTP codes covered: {', '.join(sorted(assistant.code_index.covered)) or 'none'}; "
                      f"{sum(bool(s) for s in assistant.signature_index.by_entry.values())} entries carry error signatures")

    return [_check(name, func) for name, func in (
        ("configuration", configuration), ("knowledge_base", knowledge_base), ("embedding_model", embedding_model),
        ("vector_index", vector_index), ("match_indexes", match_indexes),
    )]


def main() -> int:
    from src.assistant import build_assistant
    from src.config import SETTINGS
    from src.observability import configure_logging

    configure_logging(SETTINGS.log_level)
    checks = run_health_checks(build_assistant())
    for check in checks:
        print(json.dumps(asdict(check)))
    return 0 if all(check.ok for check in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
