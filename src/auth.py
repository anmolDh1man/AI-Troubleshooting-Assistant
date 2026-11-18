"""Optional login with Streamlit's built-in OIDC support (st.login / st.user / st.logout).

AUTH_REQUIRED=false (default): the app is open, as in local development and the demo.
AUTH_REQUIRED=true: only users logged in through the configured OIDC provider may use the app. The
provider is configured outside this repository, in the [auth] section of .streamlit/secrets.toml (or the
Streamlit Cloud secrets UI): redirect_uri, cookie_secret, client_id, client_secret, server_metadata_url.
See .streamlit/secrets.toml.example and SECURITY.md. No credentials are stored in this repository.

The app FAILS CLOSED: if login is required but the [auth] section is missing or incomplete, or Authlib
is not installed, nobody gets in and the page says that authentication is not configured.
"""

from collections.abc import Mapping

OPEN = "open"                    # login not required
ALLOWED = "allowed"              # login required and the user is logged in
NEEDS_LOGIN = "needs_login"      # login required, configured, user not logged in yet
MISCONFIGURED = "misconfigured"  # login required but not usable: block everyone

_PROVIDER_KEYS = ("client_id", "client_secret", "server_metadata_url")


def auth_section_is_complete(section: Mapping | None) -> bool:
    """[auth] has redirect_uri and cookie_secret, plus one provider (in [auth] itself or a named sub-section)."""
    if not section or not section.get("redirect_uri") or not section.get("cookie_secret"):
        return False
    if all(section.get(key) for key in _PROVIDER_KEYS):
        return True
    return any(isinstance(value, Mapping) and all(value.get(key) for key in _PROVIDER_KEYS)
               for value in section.values())


def provider_name(section: Mapping | None) -> str | None:
    """Name of the first named provider sub-section (st.login(provider)), or None for the default provider."""
    for key, value in (section or {}).items():
        if isinstance(value, Mapping) and all(value.get(k) for k in _PROVIDER_KEYS):
            return key
    return None


def decide_access(auth_required: bool, auth_configured: bool, authlib_installed: bool, is_logged_in: bool) -> str:
    if not auth_required:
        return OPEN
    if not (auth_configured and authlib_installed):
        return MISCONFIGURED
    return ALLOWED if is_logged_in else NEEDS_LOGIN


def read_auth_section() -> Mapping | None:
    """The [auth] secrets section, or None if there is no secrets file or no [auth] section."""
    try:
        import streamlit as st

        return st.secrets["auth"] if "auth" in st.secrets else None
    except Exception:
        return None
