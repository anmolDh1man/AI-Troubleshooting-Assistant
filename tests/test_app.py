"""UI smoke tests using Streamlit's AppTest (runs app.py headlessly, no browser)."""

from streamlit.testing.v1 import AppTest

from src.config import PROJECT_ROOT

APP_PATH = str(PROJECT_ROOT / "app.py")
TIMEOUT = 120  # first run loads the embedding model


def _run_query(query: str) -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=TIMEOUT).run()
    assert not at.exception
    at.chat_input[0].set_value(query).run()
    assert not at.exception
    return at


def test_app_starts_without_errors():
    at = AppTest.from_file(APP_PATH, default_timeout=TIMEOUT).run()
    assert not at.exception
    assert at.title[0].value == "AI Troubleshooting Assistant"


def test_known_issue_shows_answer_and_source():
    at = _run_query("The payment API is returning a 500 error")
    assert any("Matched KB-001" in box.value for box in at.success)
    assert any("Source used: KB-001" in exp.label for exp in at.expander)
    assert any("no LLM" in caption.value for caption in at.caption)


def test_unknown_issue_shows_no_resolution():
    at = _run_query("my laptop keyboard is not working")
    assert any("does not contain a matching entry" in box.value for box in at.info)
    assert not at.success
    assert not any("Source used" in exp.label for exp in at.expander)


def test_example_button_runs_query():
    at = AppTest.from_file(APP_PATH, default_timeout=TIMEOUT).run()
    at.sidebar.button[0].click().run()
    assert not at.exception
    assert any("KB-001" in box.value for box in at.success)
