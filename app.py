"""Streamlit chat UI for the AI Troubleshooting Assistant.

Run from the project root (with the venv activated):
    python -m streamlit run app.py
Using "python -m" runs Streamlit through the venv's python.exe instead of the
streamlit.exe launcher, which Windows Smart App Control may block.

Startup order (Phase 4): Streamlit secrets -> validated configuration -> JSON logging -> login gate
(optional OIDC) -> assistant + health checks. Any startup failure shows a generic message with a
reference ID; technical details go only to the logs.
"""

from dataclasses import asdict

import streamlit as st

from src.observability import configure_logging, get_logger, new_request_id, safe_error_fields
from src.secrets_env import SecretsError, apply_secrets, read_streamlit_secrets

st.set_page_config(page_title="AI Troubleshooting Assistant", page_icon="🛠️", layout="wide")
logger = get_logger("app")


def stop_with_error(message: str, event: str, exc: BaseException | None = None) -> None:
    """Show a safe message with a reference ID, log the details (never shown to the user), stop the run."""
    reference = new_request_id()
    fields = {"request_id": reference, **(safe_error_fields(exc) if exc else {})}
    logger.error(event, extra={"fields": fields})
    st.error(f"{message} Reference ID: {reference}.")
    st.stop()


# Must run before src.config is imported. A secrets file that exists but cannot be read stops the app:
# ignoring it could silently switch off a required login (AUTH_REQUIRED).
try:
    apply_secrets(read_streamlit_secrets())
except SecretsError as exc:
    configure_logging("INFO")
    stop_with_error("The application could not start because its secrets configuration could not be read. The "
                    "administrator can find the details in the application logs.", "invalid secrets", exc)

try:
    from src.config import SETTINGS
except Exception as exc:  # ConfigError lists the invalid settings; it goes to the log, not the page
    configure_logging("INFO")
    stop_with_error("The application could not start because its configuration is invalid. The administrator "
                    "can find the details in the application logs.", "invalid configuration", exc)

configure_logging(SETTINGS.log_level)

from src.assistant import (  # noqa: E402  (imported after the configuration has been validated)
    ANSWERED, ERROR, INVALID_INPUT, LOW_CONFIDENCE, NOT_FOUND, AssistantResponse, build_assistant,
)
from src.auth import (  # noqa: E402
    ALLOWED, MISCONFIGURED, NEEDS_LOGIN, auth_section_is_complete, decide_access, provider_name, read_auth_section,
)
from src.generator import SAFETY_NOTE  # noqa: E402
from src.health import run_health_checks  # noqa: E402
from src.rate_limit import SessionRateLimiter  # noqa: E402

EXAMPLE_QUERIES = [
    "The payment API is returning a 500 error",
    "Merchants say checkout is very slow today",
    "Customer was charged but the order shows unpaid",
    "Settlement file was not generated last night",
    "Should I restart the production database? App says too many connections",
    "Kafka consumer lag is increasing",
    "My laptop keyboard is not working",
]

STATUS_BOX = {
    ANSWERED: st.success,
    LOW_CONFIDENCE: st.warning,
    NOT_FOUND: st.info,
    INVALID_INPUT: st.info,
    ERROR: st.error,
}

@st.cache_resource(show_spinner="Loading knowledge base and embedding model...")
def get_assistant():
    """Load once per server process; Streamlit reruns this script on every interaction."""
    return build_assistant()


@st.cache_resource(show_spinner="Checking application health...")
def startup_health(_assistant):
    """Startup validation, once per server process (the leading underscore stops Streamlit hashing it)."""
    return run_health_checks(_assistant)


def is_authlib_installed() -> bool:
    try:
        from streamlit.auth_util import is_authlib_installed as check

        return check()
    except Exception:
        return False


def is_logged_in() -> bool:
    try:
        return bool(st.user.get("is_logged_in", False))
    except Exception:
        return False


def render_response(response: AssistantResponse) -> None:
    STATUS_BOX.get(response.status, st.info)(response.message)

    if response.risk_warning:
        st.error(f"⚠️ {response.risk_warning}")

    answer = response.answer
    if answer:
        st.markdown(f"**{answer.summary}**")

        st.markdown("##### 🔍 Diagnostic checks")
        st.markdown("\n".join(f"{i}. {step}" for i, step in enumerate(answer.diagnostic_steps, 1)))

        st.markdown("##### ✅ Known resolution / safe next steps")
        st.markdown("\n".join(f"- {step}" for step in answer.resolution_steps))

        if answer.approval_required:
            st.warning(
                "**Requires approval: do NOT perform without authorisation**\n\n"
                + "\n".join(f"- {action}" for action in answer.approval_required)
            )

        st.markdown("##### 📣 Escalation")
        for rule in answer.escalation:
            st.markdown(f"- **{rule.team}**: {rule.when}")

        if answer.prerequisites:
            st.caption("Prerequisites: " + "; ".join(answer.prerequisites))
        if answer.related_ids:
            st.caption("Related entries: " + ", ".join(answer.related_ids))
        st.caption(f"🧾 Generated by: **{answer.generated_by}**. Every step above is copied from the cited entry.")

    for source in response.sources:
        with st.expander(f"📄 Source used: {source.entry.id} · {source.entry.title} (similarity {source.score:.2f})"):
            st.markdown(f"**Best-matching text:** “{source.matched_text}”")
            st.json(asdict(source.entry), expanded=False)

    if response.candidates:
        # Plain markdown instead of st.table: st.table pulls in pandas, whose compiled DLLs
        # Windows Smart App Control may block on some machines.
        with st.expander("Other retrieved entries (NOT used for this answer)"):
            st.markdown("\n".join(
                f"- **{r.entry.id}** · {r.entry.title} (similarity {r.score:.2f})" for r in response.candidates
            ))

    if response.clarifying_questions:
        st.markdown("**To help further, please tell me:**")
        st.markdown("\n".join(f"- {q}" for q in response.clarifying_questions))


# ---------- Login gate (optional OIDC; fails closed when required but not configured) ----------
auth_section = read_auth_section()
access = decide_access(SETTINGS.auth_required, auth_section_is_complete(auth_section), is_authlib_installed(),
                       is_logged_in())
if access == MISCONFIGURED:
    stop_with_error("Login is required (AUTH_REQUIRED=true) but authentication is not configured, so the app is "
                    "locked. The administrator must complete the [auth] secrets (see SECURITY.md).",
                    "authentication required but not configured")
if access == NEEDS_LOGIN:
    st.title("AI Troubleshooting Assistant")
    st.info("Please log in with your organisation account to use the assistant.")
    if st.button("Log in"):
        st.login(provider_name(auth_section))
    st.stop()

# ---------- Load assistant and validate it (fail clearly, without exception details) ----------
try:
    assistant = get_assistant()
    health = startup_health(assistant)
except Exception as exc:
    stop_with_error("The assistant could not start (knowledge base, embedding model or index unavailable). The "
                    "administrator can find the details in the application logs.", "startup failed", exc)
if not all(check.ok for check in health):
    failed = ", ".join(check.name for check in health if not check.ok)
    stop_with_error(f"The assistant failed its startup checks ({failed}) and is not serving requests.",
                    "startup health check failed")

if "history" not in st.session_state:
    st.session_state.history = []  # list of (query, AssistantResponse)
if "rate_limiter" not in st.session_state:
    st.session_state.rate_limiter = SessionRateLimiter(SETTINGS.rate_limit_requests, SETTINGS.rate_limit_window_seconds)

# ---------- Sidebar ----------
with st.sidebar:
    if access == ALLOWED:
        st.caption(f"Signed in as {st.user.get('name') or st.user.get('email') or 'user'}")
        if st.button("Log out", use_container_width=True):
            st.logout()
    st.header("🛠️ About")
    st.write("Searches a **sample** L1/L2 knowledge base and suggests troubleshooting checks and escalation paths.")
    st.markdown(
        f"- Retrieval: local embeddings + ChromaDB\n"
        f"- Answer generator: **{assistant.generator.name}**\n"
        f"- Confident match ≥ {assistant.high_threshold:.2f}; possible match ≥ {assistant.low_threshold:.2f}"
    )
    st.caption(SAFETY_NOTE)

    st.subheader("Try an example")
    for example in EXAMPLE_QUERIES:
        if st.button(example, use_container_width=True):
            st.session_state.pending_query = example

    if st.button("🗑️ Clear chat", use_container_width=True):
        st.session_state.history = []

    with st.expander(f"📚 Knowledge base ({len(assistant.retriever.entries_by_id)} entries)"):
        for entry in assistant.retriever.entries_by_id.values():
            st.markdown(f"**{entry.id}** · {entry.title}  \n_{entry.category}_")

    with st.expander("🩺 System health"):
        if st.button("Run checks now", use_container_width=True):
            health = run_health_checks(assistant)
        st.markdown("\n".join(f"- {'✅' if check.ok else '❌'} **{check.name}**: {check.detail}" for check in health))
        st.caption(f"Login: {'required (OIDC)' if SETTINGS.auth_required else 'not required'} · "
                   f"Rate limit: {SETTINGS.rate_limit_requests} requests per {SETTINGS.rate_limit_window_seconds}s "
                   "per session")
    st.caption("Do not enter real customer data, card numbers, credentials or personal information.")

# ---------- Chat ----------
st.title("AI Troubleshooting Assistant")
st.caption("For L1/L2 support · Sample data only · Suggests checks, never executes actions")

# User text is shown with st.text (plain text): it is never interpreted as Markdown or HTML.
for past_query, past_response in st.session_state.history:
    with st.chat_message("user"):
        st.text(past_query)
    with st.chat_message("assistant"):
        render_response(past_response)

query = st.chat_input("Describe the issue, e.g. 'payment API returning 500 errors since 10:30'")
query = query or st.session_state.pop("pending_query", None)

if query:
    limiter = st.session_state.rate_limiter
    if not limiter.allow():
        wait = limiter.retry_after()
        logger.warning("rate limited", extra={"fields": {
            "request_id": new_request_id(), "session_requests": limiter.used, "limit": limiter.max_requests,
            "window_seconds": limiter.window_seconds}})
        st.warning(f"Too many requests from this session: the limit is {limiter.max_requests} requests per "
                   f"{int(limiter.window_seconds)} seconds. Please try again in {wait} seconds.")
    else:
        with st.chat_message("user"):
            st.text(query)
        with st.chat_message("assistant"):
            with st.spinner("Searching the knowledge base..."):
                response = assistant.ask(query)
            render_response(response)
        st.session_state.history.append((query, response))
