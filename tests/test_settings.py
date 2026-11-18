"""Configuration validation and Streamlit-secrets handling (Phase 4). No model needed.

src.config is used through the module (config.load_settings, config.ConfigError) because
tests/test_config.py reloads it, which replaces the ConfigError class object.
"""

import os

import pytest

import src.config as config
from src.secrets_env import SETTING_NAMES, SecretsError, apply_secrets, read_streamlit_secrets


def test_defaults_are_valid():
    settings = config.load_settings({})
    assert settings.top_k == 3
    assert (settings.low_confidence_threshold, settings.high_confidence_threshold) == (0.30, 0.45)
    assert settings.generator == "template" and settings.log_level == "INFO"
    assert settings.auth_required is False
    assert settings.embedding_model_revision  # pinned by default


@pytest.mark.parametrize("env, problem", [
    ({"TOP_K": "three"}, "TOP_K must be an integer"),
    ({"TOP_K": "0"}, "TOP_K must be between 1 and 20"),
    ({"TOP_K": "2.5"}, "TOP_K must be an integer"),
    ({"HIGH_CONFIDENCE_THRESHOLD": "1.5"}, "HIGH_CONFIDENCE_THRESHOLD must be between"),
    ({"LOW_CONFIDENCE_THRESHOLD": "-0.1"}, "LOW_CONFIDENCE_THRESHOLD must be between"),
    ({"LOW_CONFIDENCE_THRESHOLD": "abc"}, "LOW_CONFIDENCE_THRESHOLD must be a number"),
    ({"LOW_CONFIDENCE_THRESHOLD": "0.5", "HIGH_CONFIDENCE_THRESHOLD": "0.45"}, "must be lower than"),
    ({"LOW_CONFIDENCE_THRESHOLD": "0.45", "HIGH_CONFIDENCE_THRESHOLD": "0.45"}, "must be lower than"),
    ({"GENERATOR": "gpt"}, "GENERATOR must be one of template"),
    ({"LOG_LEVEL": "VERBOSE"}, "LOG_LEVEL must be one of"),
    ({"AUTH_REQUIRED": "maybe"}, "AUTH_REQUIRED must be true or false"),
    ({"RATE_LIMIT_REQUESTS": "0"}, "RATE_LIMIT_REQUESTS must be between"),
    ({"RATE_LIMIT_WINDOW_SECONDS": "soon"}, "RATE_LIMIT_WINDOW_SECONDS must be an integer"),
    ({"EMBEDDING_MODEL": "  "}, "EMBEDDING_MODEL must not be empty"),
    ({"CHROMA_DIR": ""}, "CHROMA_DIR must not be empty"),
])
def test_invalid_settings_are_rejected(env, problem):
    with pytest.raises(config.ConfigError, match=problem):
        config.load_settings(env)


def test_all_problems_are_reported_together_without_echoing_values():
    with pytest.raises(config.ConfigError) as info:
        config.load_settings({"TOP_K": "s3cr3t-value", "LOG_LEVEL": "nope", "GENERATOR": "x"})
    message = str(info.value)
    assert "TOP_K" in message and "LOG_LEVEL" in message and "GENERATOR" in message
    assert "s3cr3t-value" not in message  # invalid values are never repeated in errors or logs


@pytest.mark.parametrize("raw, expected", [("true", True), ("1", True), ("YES", True), ("false", False), ("0", False)])
def test_auth_required_flag(raw, expected):
    assert config.load_settings({"AUTH_REQUIRED": raw}).auth_required is expected


def test_empty_revision_means_latest():
    assert config.load_settings({"EMBEDDING_MODEL_REVISION": ""}).embedding_model_revision is None


def test_every_setting_is_documented_and_bridged_from_secrets():
    example = (config.PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    operations = (config.PROJECT_ROOT / "OPERATIONS.md").read_text(encoding="utf-8")
    for name in config.DEFAULTS:
        assert name in example, f"{name} missing from .env.example"
        assert name in operations, f"{name} missing from OPERATIONS.md"
    assert set(SETTING_NAMES) == set(config.DEFAULTS)


def test_secrets_fill_missing_settings_but_environment_wins():
    environ = {"TOP_K": "5"}
    copied = apply_secrets({"TOP_K": 7, "LOG_LEVEL": "DEBUG", "AUTH_REQUIRED": True}, environ)
    assert environ == {"TOP_K": "5", "LOG_LEVEL": "DEBUG", "AUTH_REQUIRED": "true"}
    assert sorted(copied) == ["AUTH_REQUIRED", "LOG_LEVEL"]


def test_secret_sections_and_unknown_keys_never_enter_the_environment():
    environ = {}
    secrets = {
        "auth": {"client_secret": "do-not-copy", "cookie_secret": "do-not-copy"},
        "SOME_API_KEY": "do-not-copy",
    }
    assert apply_secrets(secrets, environ) == []
    assert environ == {}


@pytest.mark.parametrize("value", [{"nested": 1}, ["true"]])
def test_known_setting_with_unusable_type_is_an_error_not_ignored(value):
    with pytest.raises(SecretsError, match="AUTH_REQUIRED has an unsupported type"):
        apply_secrets({"AUTH_REQUIRED": value}, {})


# --- AUTH_REQUIRED=true can never be silently discarded -------------------------------------------

@pytest.mark.parametrize("env_value, secret_value", [("false", True), ("0", "true"), ("", "yes")])
def test_login_required_in_secrets_wins_over_environment_false(env_value, secret_value):
    environ = {"AUTH_REQUIRED": env_value}
    apply_secrets({"AUTH_REQUIRED": secret_value}, environ)
    assert environ["AUTH_REQUIRED"] == "true"


def test_login_required_in_environment_is_not_switched_off_by_secrets():
    environ = {"AUTH_REQUIRED": "true"}
    apply_secrets({"AUTH_REQUIRED": False}, environ)
    assert environ["AUTH_REQUIRED"] == "true"


# --- Real secrets files: missing, malformed, unreadable, valid -------------------------------------

@pytest.fixture
def secrets_files(monkeypatch):
    """Point Streamlit at chosen secrets paths and give it a fresh (unparsed) secrets object."""
    import streamlit
    from streamlit import config as st_config
    from streamlit.runtime.secrets import Secrets, secrets_singleton

    real_get_option = st_config.get_option
    paths: list[str] = []
    monkeypatch.setattr(st_config, "get_option",
                        lambda key: list(paths) if key == "secrets.files" else real_get_option(key))
    monkeypatch.setattr(streamlit, "secrets", Secrets())
    # Streamlit's auth helpers parse the internal singleton directly; keep its cache isolated as well.
    monkeypatch.setattr(secrets_singleton, "_secrets", None)
    for name in SETTING_NAMES:  # Streamlit exports top-level secrets to os.environ; restore afterwards
        if name in os.environ:
            monkeypatch.setenv(name, os.environ[name])
        else:
            monkeypatch.delenv(name, raising=False)
    return paths


def test_missing_secrets_file_is_not_an_error(secrets_files, tmp_path):
    secrets_files.append(str(tmp_path / "absent" / "secrets.toml"))
    assert read_streamlit_secrets() == {}


def test_missing_secrets_file_in_the_project_is_not_an_error():
    assert read_streamlit_secrets() == {}  # tests run without .streamlit/secrets.toml


def test_malformed_secrets_file_is_a_safe_error(secrets_files, tmp_path):
    path = tmp_path / "secrets.toml"
    path.write_text('AUTH_REQUIRED = true\n[auth\nclient_secret = "SHOULD-NOT-LEAK"\n', encoding="utf-8")
    secrets_files.append(str(path))
    with pytest.raises(SecretsError) as info:
        read_streamlit_secrets()
    assert "SHOULD-NOT-LEAK" not in str(info.value) and str(path) not in str(info.value)
    assert info.value.__cause__ is None  # the parser's message (which may quote the file) is not chained


def test_unreadable_secrets_directory_is_a_safe_error(secrets_files, tmp_path):
    secrets_dir = tmp_path / "k8s-secrets"
    secrets_dir.mkdir()
    (secrets_dir / "not-a-folder.txt").write_text("x", encoding="utf-8")  # Streamlit requires sub-folders
    secrets_files.append(str(secrets_dir))
    with pytest.raises(SecretsError):
        read_streamlit_secrets()


def test_valid_secrets_file_is_read_and_environment_still_wins(secrets_files, tmp_path, monkeypatch):
    path = tmp_path / "secrets.toml"
    path.write_text('AUTH_REQUIRED = true\nLOG_LEVEL = "DEBUG"\n[auth]\nredirect_uri = "placeholder"\n', encoding="utf-8")
    secrets_files.append(str(path))
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    secrets = read_streamlit_secrets()
    assert secrets["AUTH_REQUIRED"] is True and "auth" in secrets
    assert os.environ["LOG_LEVEL"] == "WARNING"  # Streamlit's own export did not override the environment
    apply_secrets(secrets)
    assert os.environ["AUTH_REQUIRED"] == "true"  # login required by the secrets file is kept
    assert os.environ["LOG_LEVEL"] == "WARNING"
    assert "redirect_uri" not in os.environ
