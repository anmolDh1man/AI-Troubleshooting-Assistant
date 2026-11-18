"""Copy supported settings from Streamlit secrets into the environment (used by app.py).

Kept separate from src/config.py, which reads the environment when it is imported: app.py calls
apply_secrets(read_streamlit_secrets()) first, then imports the rest of the application.

Rules:
  - A secrets file that is ABSENT is normal (local runs, tests): environment, .env and defaults apply.
    A secrets file that EXISTS but cannot be read or parsed is a configuration error (SecretsError):
    the app must not start, because silently ignoring it could switch off a required login.
  - Real environment variables win over secrets for every setting, except that AUTH_REQUIRED=true from
    either source wins: login can be switched on by any source, never silently switched off by another.
  - Only the known setting names are copied by this module. A known setting with an unusable type
    (e.g. a list or table) is an error, not silently ignored.
  - Sections such as [auth] (OIDC client secret, cookie secret) are never copied: Streamlit reads them
    directly. Note that Streamlit itself exports top-level string/number secrets to the process
    environment; keep credentials inside sections, never as top-level keys.
"""

import os
from collections.abc import Mapping, MutableMapping

SETTING_NAMES = (
    "CHROMA_DIR", "EMBEDDING_MODEL", "EMBEDDING_MODEL_REVISION", "GENERATOR", "TOP_K",
    "HIGH_CONFIDENCE_THRESHOLD", "LOW_CONFIDENCE_THRESHOLD", "LOG_LEVEL",
    "RATE_LIMIT_REQUESTS", "RATE_LIMIT_WINDOW_SECONDS", "AUTH_REQUIRED",
)
_TRUE = ("1", "true", "yes", "on")


class SecretsError(Exception):
    """The secrets file exists but cannot be used. The message never contains secret values."""


def _as_text(value) -> str | None:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    return None


def apply_secrets(secrets: Mapping, environ: MutableMapping[str, str] | None = None) -> list[str]:
    """Copy known top-level settings from `secrets` into `environ`; return the names written."""
    environ = os.environ if environ is None else environ
    written = []
    for name in SETTING_NAMES:
        if name not in secrets:
            continue
        value = _as_text(secrets[name])
        if value is None:
            raise SecretsError(f"Secret setting {name} has an unsupported type ({type(secrets[name]).__name__}); "
                               "use a string, number or true/false")
        if name not in environ:
            environ[name] = value
            written.append(name)
        elif name == "AUTH_REQUIRED" and value.strip().lower() in _TRUE \
                and environ[name].strip().lower() not in _TRUE:
            environ[name] = "true"  # a required login is never discarded by another source
            written.append(name)
    return written


def read_streamlit_secrets() -> Mapping:
    """st.secrets as a plain mapping; {} only when no secrets file exists.

    Raises SecretsError when a configured secrets file or directory exists but cannot be parsed.
    Environment values of the known settings are restored afterwards, because Streamlit exports
    top-level secrets to os.environ and would otherwise override the real environment.
    """
    import streamlit as st
    from streamlit import config as st_config

    original = {name: os.environ[name] for name in SETTING_NAMES if name in os.environ}
    try:
        secrets = {key: st.secrets[key] for key in st.secrets.keys()}
    except Exception as exc:
        try:
            paths = list(st_config.get_option("secrets.files") or [])
        except Exception:
            paths = []
        if any(os.path.exists(path) for path in paths):
            raise SecretsError(f"A secrets file exists but could not be read ({type(exc).__name__}). Check its "
                               "TOML syntax and file permissions.") from None
        return {}
    finally:
        for name in SETTING_NAMES:  # undo Streamlit's export for our settings: the environment wins
            if name in original:
                os.environ[name] = original[name]
    return secrets
