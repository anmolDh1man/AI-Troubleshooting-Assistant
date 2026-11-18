"""Configuration tests, including ChromaDB test isolation."""

import importlib

import src.config as config


def test_tests_never_use_the_project_chroma_index():
    # tests/conftest.py points CHROMA_DIR at a temporary folder before src.config is imported.
    assert config.CHROMA_DIR != config.PROJECT_ROOT / "chroma_db"
    assert config.PROJECT_ROOT not in config.CHROMA_DIR.parents


def test_chroma_dir_can_be_overridden_by_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path / "custom_index"))
    try:
        assert importlib.reload(config).CHROMA_DIR == tmp_path / "custom_index"
    finally:
        monkeypatch.undo()
        importlib.reload(config)


def test_chroma_dir_defaults_to_project_folder(monkeypatch):
    monkeypatch.delenv("CHROMA_DIR", raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)  # ignore any local .env
    try:
        assert importlib.reload(config).CHROMA_DIR == config.PROJECT_ROOT / "chroma_db"
    finally:
        monkeypatch.undo()
        importlib.reload(config)
