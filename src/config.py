"""Central configuration, read from environment variables (.env) with safe defaults.

Every setting is validated once at import time (type, range, threshold ordering). An invalid value
raises ConfigError listing every problem, so the app fails at startup with a clear message instead of
misbehaving later. Values come from, in order of precedence:
  1. real environment variables (e.g. Docker, CI),
  2. Streamlit secrets (top-level keys; copied into the environment by app.py before this import),
  3. a local .env file (python-dotenv never overrides variables that are already set),
  4. the defaults below.
Exception: AUTH_REQUIRED=true from secrets wins over a false environment value (src/secrets_env.py).
All supported settings are documented in .env.example and OPERATIONS.md.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

KB_PATH = PROJECT_ROOT / "data" / "knowledge_base.json"

SUPPORTED_GENERATORS = ("template",)
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
_TRUE, _FALSE = ("1", "true", "yes", "on"), ("0", "false", "no", "off", "")

# Setting name -> default. These are the only settings read from the environment / Streamlit secrets.
DEFAULTS = {
    "CHROMA_DIR": str(PROJECT_ROOT / "chroma_db"),
    "EMBEDDING_MODEL": "sentence-transformers/all-MiniLM-L6-v2",
    # Hugging Face commit of the model used for every recorded evaluation (pinned for reproducibility).
    # Set to an empty value to follow the latest revision instead.
    "EMBEDDING_MODEL_REVISION": "1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
    "GENERATOR": "template",
    "TOP_K": "3",
    # Calibrated with scripts/calibrate_retrieval.py (see results/retrieval_calibration.csv):
    #   score >= HIGH            -> confident match, answer from the entry
    #   LOW <= score < HIGH      -> possible match, show it with a warning and ask for details
    #   score < LOW              -> not covered by the knowledge base
    "HIGH_CONFIDENCE_THRESHOLD": "0.45",
    "LOW_CONFIDENCE_THRESHOLD": "0.30",
    "LOG_LEVEL": "INFO",
    "RATE_LIMIT_REQUESTS": "30",        # per browser session ...
    "RATE_LIMIT_WINDOW_SECONDS": "60",  # ... within this many seconds
    "AUTH_REQUIRED": "false",           # true = only users logged in through OIDC may use the app
}


class ConfigError(Exception):
    """One or more settings are missing or invalid."""


@dataclass(frozen=True)
class Settings:
    chroma_dir: Path
    embedding_model: str
    embedding_model_revision: str | None
    generator: str
    top_k: int
    high_confidence_threshold: float
    low_confidence_threshold: float
    log_level: str
    rate_limit_requests: int
    rate_limit_window_seconds: int
    auth_required: bool


def _number(raw: str, name: str, kind, low, high, errors: list[str]):
    try:
        value = kind(raw.strip())
    except ValueError:
        errors.append(f"{name} must be {'an integer' if kind is int else 'a number'} (got a non-numeric value)")
        return None
    if not low <= value <= high:
        errors.append(f"{name} must be between {low} and {high}")
        return None
    return value


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Read and validate all settings. Raises ConfigError listing every invalid setting."""
    env = os.environ if env is None else env
    raw = {name: str(env.get(name, default)) for name, default in DEFAULTS.items()}
    errors: list[str] = []

    top_k = _number(raw["TOP_K"], "TOP_K", int, 1, 20, errors)
    high = _number(raw["HIGH_CONFIDENCE_THRESHOLD"], "HIGH_CONFIDENCE_THRESHOLD", float, 0.0, 1.0, errors)
    low = _number(raw["LOW_CONFIDENCE_THRESHOLD"], "LOW_CONFIDENCE_THRESHOLD", float, 0.0, 1.0, errors)
    if high is not None and low is not None and not low < high:
        errors.append("LOW_CONFIDENCE_THRESHOLD must be lower than HIGH_CONFIDENCE_THRESHOLD")
    requests = _number(raw["RATE_LIMIT_REQUESTS"], "RATE_LIMIT_REQUESTS", int, 1, 10_000, errors)
    window = _number(raw["RATE_LIMIT_WINDOW_SECONDS"], "RATE_LIMIT_WINDOW_SECONDS", int, 1, 86_400, errors)

    generator = raw["GENERATOR"].strip().lower()
    if generator not in SUPPORTED_GENERATORS:
        errors.append(f"GENERATOR must be one of {', '.join(SUPPORTED_GENERATORS)}")
    model = raw["EMBEDDING_MODEL"].strip()
    if not model:
        errors.append("EMBEDDING_MODEL must not be empty")
    log_level = raw["LOG_LEVEL"].strip().upper()
    if log_level not in LOG_LEVELS:
        errors.append(f"LOG_LEVEL must be one of {', '.join(LOG_LEVELS)}")
    auth = raw["AUTH_REQUIRED"].strip().lower()
    if auth not in _TRUE + _FALSE:
        errors.append("AUTH_REQUIRED must be true or false")
    chroma_dir = raw["CHROMA_DIR"].strip()
    if not chroma_dir:
        errors.append("CHROMA_DIR must not be empty")

    if errors:
        raise ConfigError("Invalid configuration:\n  - " + "\n  - ".join(errors))
    return Settings(
        chroma_dir=Path(chroma_dir),
        embedding_model=model,
        embedding_model_revision=raw["EMBEDDING_MODEL_REVISION"].strip() or None,
        generator=generator,
        top_k=top_k,
        high_confidence_threshold=high,
        low_confidence_threshold=low,
        log_level=log_level,
        rate_limit_requests=requests,
        rate_limit_window_seconds=window,
        auth_required=auth in _TRUE,
    )


SETTINGS = load_settings()

# Module-level names kept for the rest of the code base.
# Overridable so tests (and other environments) never touch the app's own index.
CHROMA_DIR = SETTINGS.chroma_dir
EMBEDDING_MODEL = SETTINGS.embedding_model
EMBEDDING_MODEL_REVISION = SETTINGS.embedding_model_revision
GENERATOR = SETTINGS.generator
TOP_K = SETTINGS.top_k
HIGH_CONFIDENCE_THRESHOLD = SETTINGS.high_confidence_threshold
LOW_CONFIDENCE_THRESHOLD = SETTINGS.low_confidence_threshold
