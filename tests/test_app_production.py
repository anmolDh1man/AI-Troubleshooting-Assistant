"""Production-readiness behaviour of the Streamlit app (Phase 4), run headlessly with AppTest.

OIDC is tested without any real identity provider: the [auth] values below are obvious placeholders,
st.login is never called, and the logged-in state is simulated by replacing st.user.
"""

import dataclasses
import sys

import pytest
import streamlit
from streamlit.testing.v1 import AppTest

import src.config as config
from src.auth import ALLOWED, MISCONFIGURED, NEEDS_LOGIN, OPEN, auth_section_is_complete, decide_access, provider_name

APP_PATH = str(config.PROJECT_ROOT / "app.py")
TIMEOUT = 120
PLACEHOLDER_AUTH = {  # not real credentials; never used to contact anything
    "redirect_uri": "http://localhost:8501/oauth2callback",
    "cookie_secret": "test-only-placeholder-cookie-secret",
    "client_id": "test-only-client-id",
    "client_secret": "test-only-client-secret",
    "server_metadata_url": "https://idp.example.invalid/.well-known/openid-configuration",
}


def _settings(monkeypatch, **changes):
    monkeypatch.setattr(config, "SETTINGS", dataclasses.replace(config.SETTINGS, **changes))


def _app(secrets=None) -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=TIMEOUT)
    if secrets:
        at.secrets.update(secrets)
    return at.run()


# --- OIDC gate: decision logic -----------------------------------------------------------------

@pytest.mark.parametrize("required, configured, authlib, logged_in, expected", [
    (False, False, False, False, OPEN),
    (False, True, True, False, OPEN),
    (True, False, True, False, MISCONFIGURED),   # fail closed: required but not configured
    (True, True, False, False, MISCONFIGURED),   # fail closed: Authlib missing
    (True, True, True, False, NEEDS_LOGIN),
    (True, True, True, True, ALLOWED),
])
def test_access_decision(required, configured, authlib, logged_in, expected):
    assert decide_access(required, configured, authlib, logged_in) == expected


def test_auth_section_completeness():
    assert auth_section_is_complete(PLACEHOLDER_AUTH)
    assert not auth_section_is_complete(None)
    assert not auth_section_is_complete({k: v for k, v in PLACEHOLDER_AUTH.items() if k != "cookie_secret"})
    assert not auth_section_is_complete({**PLACEHOLDER_AUTH, "client_secret": ""})
    named = {"redirect_uri": "http://localhost:8501/oauth2callback", "cookie_secret": "x",
             "corp": {k: PLACEHOLDER_AUTH[k] for k in ("client_id", "client_secret", "server_metadata_url")}}
    assert auth_section_is_complete(named) and provider_name(named) == "corp"
    assert provider_name(PLACEHOLDER_AUTH) is None


# --- OIDC gate: in the app ---------------------------------------------------------------------

def test_login_required_but_not_configured_locks_the_app(monkeypatch):
    _settings(monkeypatch, auth_required=True)
    at = _app()
    assert not at.exception
    assert any("authentication is not configured" in e.value and "Reference ID" in e.value for e in at.error)
    assert not at.chat_input  # nobody can use the assistant


def test_login_required_and_configured_asks_for_login(monkeypatch):
    _settings(monkeypatch, auth_required=True)
    at = _app({"auth": PLACEHOLDER_AUTH})
    assert not at.exception
    assert any(button.label == "Log in" for button in at.button)
    assert not at.chat_input


def test_logged_in_user_can_use_the_app(monkeypatch):
    _settings(monkeypatch, auth_required=True)
    monkeypatch.setattr(streamlit, "user", {"is_logged_in": True, "name": "Test User"})
    at = _app({"auth": PLACEHOLDER_AUTH})
    assert not at.exception
    assert at.chat_input
    assert any("Signed in as Test User" in caption.value for caption in at.sidebar.caption)


def test_app_is_open_when_login_is_not_required():
    at = _app()
    assert at.chat_input
    assert any("Login: not required" in caption.value for caption in at.sidebar.caption)


# --- Secrets file: malformed, valid, missing (the login requirement can never be silently dropped) ---

@pytest.fixture
def secrets_file(monkeypatch, tmp_path):
    """Point Streamlit at one secrets file in tmp_path (content written by the test) and re-read settings."""
    import os

    from streamlit import config as st_config
    from streamlit.runtime.secrets import Secrets, secrets_singleton

    path = tmp_path / "secrets.toml"
    real_get_option = st_config.get_option
    monkeypatch.setattr(st_config, "get_option",
                        lambda key: [str(path)] if key == "secrets.files" else real_get_option(key))
    monkeypatch.setattr(streamlit, "secrets", Secrets())
    # Streamlit's auth helpers parse the internal singleton directly; keep its cache isolated as well.
    monkeypatch.setattr(secrets_singleton, "_secrets", None)
    monkeypatch.delitem(sys.modules, "src.config")  # the app re-imports the configuration after applying secrets
    for name in ("AUTH_REQUIRED", "LOG_LEVEL"):
        monkeypatch.delenv(name, raising=False)
    yield path
    for name in ("AUTH_REQUIRED", "LOG_LEVEL"):  # values the app copied from the secrets file
        os.environ.pop(name, None)


def test_malformed_secrets_file_stops_the_app_safely(secrets_file):
    secrets_file.write_text('AUTH_REQUIRED = true\n[auth\nclient_secret = "SHOULD-NOT-LEAK"\n', encoding="utf-8")
    at = _app()
    assert not at.exception
    errors = " ".join(e.value for e in at.error)
    assert "secrets configuration could not be read" in errors and "Reference ID" in errors
    assert "SHOULD-NOT-LEAK" not in errors and str(secrets_file) not in errors
    assert not at.chat_input  # never falls back to open mode


def test_login_required_in_secrets_file_is_enforced(secrets_file):
    secrets_file.write_text("AUTH_REQUIRED = true\n", encoding="utf-8")  # no [auth] section: fail closed
    at = _app()
    assert not at.exception
    assert any("authentication is not configured" in e.value for e in at.error)
    assert not at.chat_input


def test_missing_secrets_file_keeps_the_documented_default(secrets_file):
    assert not secrets_file.exists()
    at = _app()
    assert not at.exception
    assert at.chat_input  # AUTH_REQUIRED defaults to false: the app is open, as documented


# --- Rate limiting, health, safe errors ----------------------------------------------------------

def test_session_rate_limit_blocks_extra_requests(monkeypatch):
    _settings(monkeypatch, rate_limit_requests=2, rate_limit_window_seconds=60)
    at = _app()
    for query in ("payment API returns 500", "checkout is slow", "settlement file missing"):
        at.chat_input[0].set_value(query).run()
    assert not at.exception
    assert any("Too many requests from this session" in w.value for w in at.warning)
    assert len(at.session_state.history) == 2


def test_health_panel_shows_all_checks():
    at = _app()
    text = "\n".join(m.value for m in at.sidebar.markdown)
    for name in ("configuration", "knowledge_base", "embedding_model", "vector_index", "match_indexes"):
        assert f"✅ **{name}**" in text


def test_invalid_configuration_shows_a_safe_error(monkeypatch):
    monkeypatch.setenv("TOP_K", "not-a-number-SECRETVALUE")
    monkeypatch.delitem(sys.modules, "src.config")  # force a fresh, failing import inside the app run
    at = _app()
    assert not at.exception
    errors = " ".join(e.value for e in at.error)
    assert "configuration is invalid" in errors and "Reference ID" in errors
    assert "SECRETVALUE" not in errors and "TOP_K" not in errors
    assert not at.chat_input


def test_startup_failure_shows_no_exception_details(monkeypatch):
    import src.assistant

    def broken_build():
        raise OSError("model files missing at C:/internal/secret/path")

    streamlit.cache_resource.clear()
    monkeypatch.setattr(src.assistant, "build_assistant", broken_build)
    try:
        at = _app()
        errors = " ".join(e.value for e in at.error)
        assert "could not start" in errors and "Reference ID" in errors
        assert "secret/path" not in errors and "OSError" not in errors
        assert not at.chat_input
    finally:
        streamlit.cache_resource.clear()  # later tests rebuild the real assistant
