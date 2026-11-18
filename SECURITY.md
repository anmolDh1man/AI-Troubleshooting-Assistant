# Security

Security controls of the AI Troubleshooting Assistant, what each one does **not** cover, and what still
needs external configuration. Operations details are in [OPERATIONS.md](OPERATIONS.md).

> **Not production-ready.** This is a prototype with **simulated sample data**. It has not had a security
> review or penetration test, and the Phase 2–4 changes are not deployed.
> **Do not enter real customer data:** no card numbers (PAN), account details, credentials, tokens or
> personal information.

## What the assistant can and cannot do

- It only searches a small, curated JSON knowledge base and displays its text. It cannot execute
  commands, connect to systems, or change anything. Disruptive actions are only *shown* as items that
  need approval.
- There is no LLM, so prompt injection cannot change its behaviour. Injection-style input is still refused
  before retrieval (input hygiene, not a security boundary).
- It stores nothing persistently about users or queries. Chat history lives only in the browser session.

## Controls

| Area | Control | Limits |
|---|---|---|
| Authentication | Optional OIDC login with Streamlit's built-in `st.login` (`AUTH_REQUIRED=true` + `[auth]` secrets). **Fails closed**: if login is required but `[auth]` is incomplete or Authlib is missing, the app is locked for everyone. A secrets file that exists but cannot be parsed stops the app instead of being ignored. `AUTH_REQUIRED=true` from either the environment or secrets wins, so a required login cannot be silently switched off | **Not configured**: no identity provider has been set up, and real login has never been exercised. Login is tested only with placeholder values and a simulated logged-in user. No roles or authorisation: every logged-in user has the same access |
| Secrets | Read from Streamlit secrets or environment variables; `.env` and `.streamlit/secrets.toml` are git-ignored and excluded from Docker images; only placeholder templates are committed (`.env.example`, `.streamlit/secrets.toml.example`). The `[auth]` section is never copied into the process environment | Secret storage and rotation depend on the hosting platform. Streamlit itself exports **top-level** string/number secrets to the process environment, so keep credentials inside sections such as `[auth]`, never as top-level keys |
| Configuration | All settings validated at startup; the app refuses to start on invalid values; values are never echoed in errors or logs | — |
| Error handling | Users see generic messages with a reference ID. Exception text and tracebacks never reach the page (`client.showErrorDetails = "none"`). Details go to the logs | — |
| Logging | JSON, metadata only (allow-listed fields). Query text is never logged, and the query is scrubbed from logged tracebacks. No credentials or user identity are logged | Logs go to stderr only. Storage, access control and retention are **not configured** |
| Rate limiting | Per browser session (default 30 requests / 60 s) | **Not** global or per IP: a new session resets it. Needs a reverse proxy / gateway / WAF (**not configured**) |
| Input handling | Length limits, Unicode normalisation, injection and markup refusal; user text is rendered as plain text (`st.text`) | Pattern-based; reworded injections can pass (harmless, since there is no LLM) |
| Network | Local runs bind to `localhost`. The container listens on `0.0.0.0:8501` and must sit behind a TLS reverse proxy | TLS termination and network policy are **not configured** |
| Container | Non-root user, slim base image, no secrets in the image, offline model at runtime | Image **not built or scanned** (Docker unavailable). No vulnerability scanning in CI |
| Dependencies | Pinned top-level versions | Transitive versions not locked; no automated vulnerability scanning |

## Setting up OIDC login (external configuration required)

1. Register the app with your identity provider (e.g. Microsoft Entra ID, Google, Okta, Auth0). Set the
   redirect URI to `https://<your-host>/oauth2callback`.
2. Put the provider's values in `.streamlit/secrets.toml` (git-ignored) or in the Streamlit Cloud secrets,
   using `.streamlit/secrets.toml.example` as the template. Generate a long random `cookie_secret`.
3. Set `AUTH_REQUIRED=true` and restart. Check that an unauthenticated browser only sees the *Log in*
   button, and that login and logout work.

Without step 2, `AUTH_REQUIRED=true` locks the app (fail closed). With `AUTH_REQUIRED=false` (the default)
the app is open to anyone who can reach it. Use that only on `localhost` or a trusted network.

## Reporting a problem

Report suspected vulnerabilities privately to the repository owner, not in a public issue. Include the
reference ID shown in the app, if any.
