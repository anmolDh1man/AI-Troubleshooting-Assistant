# Operations guide

How to run, configure, monitor and recover the AI Troubleshooting Assistant. Security controls and their
limits are described in [SECURITY.md](SECURITY.md).

> **Status:** prototype with production-readiness controls added in Phase 4. It has **not** been deployed
> with these changes. The live Streamlit Community Cloud demo still runs the original `master` version.
> The Docker image and the CI workflow have been **written but not executed**: Docker is not installed on
> the development machine, and nothing has been pushed to GitHub.

## 1. Settings

Every setting is validated at startup (type, range, threshold ordering). If any value is invalid, the app
stops with "configuration is invalid" and a reference ID. The log line with that reference ID lists every
invalid setting name. Values are never echoed.

Precedence: **real environment variables > Streamlit secrets (top-level keys) > `.env` > defaults**, with two
safety rules:
- **`AUTH_REQUIRED=true` from any source wins.** Login can be switched on by the environment or by secrets,
  but never silently switched off by the other.
- **Secrets file states.** If a secrets file is absent, that's normal (local runs). If it exists but can't
  be parsed or read, the app refuses to start ("secrets configuration could not be read", with a reference
  ID). It does not silently fall back to open mode.

A known setting given in secrets with an unusable type (e.g. a list) is also a startup error.

| Setting | Default | Allowed values | Purpose |
|---|---|---|---|
| `CHROMA_DIR` | `<project>/chroma_db` | non-empty path | Folder of the local ChromaDB vector index (generated data) |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | non-empty | Local embedding model |
| `EMBEDDING_MODEL_REVISION` | `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` | commit hash, or empty for latest | Pinned model version (the one used in all recorded evaluations) |
| `GENERATOR` | `template` | `template` | Answer generator (rule-based, no LLM) |
| `TOP_K` | `3` | integer 1–20 | Entries shown per query |
| `HIGH_CONFIDENCE_THRESHOLD` | `0.45` | 0–1, greater than LOW | At or above: confident answer |
| `LOW_CONFIDENCE_THRESHOLD` | `0.30` | 0–1, lower than HIGH | Below: not found |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` | Application log level |
| `RATE_LIMIT_REQUESTS` | `30` | integer 1–10000 | Requests allowed per browser session per window |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | integer 1–86400 | Rate-limit window |
| `AUTH_REQUIRED` | `false` | `true` / `false` | Require OIDC login (see SECURITY.md) |

Changing a threshold changes answer behaviour. Re-run the calibration and the regression tests first:
`python -m scripts.calibrate_retrieval --tag <name>` and `python -m pytest -q`.

## 2. Running

**Local (Windows PowerShell):**
```powershell
pip install -r requirements-dev.txt           # runtime + pytest (requirements.txt = runtime only)
python -m streamlit run app.py                # http://localhost:8501, bound to localhost only
```

**Docker** (prepared, **not verified**: Docker was not available when this was written):
```bash
docker build -t ai-troubleshooting-assistant .
docker run --rm -p 8501:8501 ai-troubleshooting-assistant
# with settings / secrets:
docker run --rm -p 8501:8501 -e LOG_LEVEL=WARNING \
  -v "$PWD/secrets.toml:/app/.streamlit/secrets.toml:ro" ai-troubleshooting-assistant
```
The image uses Python 3.12-slim, CPU-only PyTorch, and a non-root user (`app`, uid 10001). The pinned
embedding model is downloaded at build time, and the container runs with `HF_HUB_OFFLINE=1`. Inside the
container the server listens on `0.0.0.0:8501`; the local `.streamlit/config.toml` keeps `localhost` for
non-container runs. Put the container behind a reverse proxy with TLS. Never publish port 8501 directly
to the internet.

**Streamlit Community Cloud:** deploy from a branch, set the settings and the `[auth]` section in the app's
*Secrets* settings (same format as `.streamlit/secrets.toml.example`), and redeploy. This has **not** been
done for the Phase 2–4 code.

## 3. Health checks

| Check | What it verifies |
|---|---|
| `configuration` | All settings valid |
| `knowledge_base` | KB file valid, and the same entries as the running app (otherwise a restart is needed) |
| `embedding_model` | Model loaded and returns vectors (fixed probe sentence, never user input) |
| `vector_index` | Index fingerprint matches the KB and model, and every chunk is present |
| `match_indexes` | HTTP-code and error-signature indexes cover every KB entry |

- **At startup** the checks run once per server process. If any check fails, the app shows an error with a
  reference ID and serves no requests.
- **In the app:** sidebar → *System health* → *Run checks now*.
- **Command line** (also inside a container: `docker exec <container> python -m src.health`):
  `python -m src.health` prints one JSON line per check and exits with code 1 if any check fails.
- **Container liveness:** the Docker `HEALTHCHECK` calls Streamlit's `/_stcore/health`. This shows that the
  server is up, **not** that the checks above pass.

## 4. Logs

The application logs JSON lines on stderr (Docker: `docker logs`; Streamlit Cloud: *Manage app → Logs*).
One `request` event is written per query:

```json
{"timestamp": "2026-11-16T09:12:03.512+00:00", "level": "INFO", "logger": "troubleshooting.assistant",
 "event": "request", "request_id": "3f9c1a2b7d4e", "status": "answered", "matched_entry": "KB-001",
 "score": 0.7012, "confidence_zone": "answered", "latency_ms": 41.3, "risk_warning": false,
 "refusal": null, "uncovered_codes": null, "error_type": null, "query_length": 41}
```

Other events: `retrieval failed`, `vector index unavailable`, `generator failed`, `unexpected error`
(with `error_type` and a traceback in which the query text is replaced by `[query]`), `rate limited`,
`health check failed`, `invalid configuration`, `invalid secrets`, `startup failed`, and `authentication
required but not configured`.

- **Never logged:** query text, credentials, secrets, or user identity. Only an allow-list of metadata
  fields can appear in a log line.
- **Reference IDs:** every error shown to a user includes a reference ID. Search the logs for that
  `request_id`.
- **Not provided:** log storage, retention, search or alerting. Streamlit Cloud and `docker logs` keep only
  recent output. Ship stderr to a log platform (e.g. ELK, Loki, CloudWatch) and add alerts on `level: ERROR`.
  This is an external dependency that is **not configured**.

## 5. Rate limiting

- **Per browser session:** `RATE_LIMIT_REQUESTS` per `RATE_LIMIT_WINDOW_SECONDS`, using a sliding window
  in `st.session_state`.
- **Not global and not per IP:** a reload or a new tab starts a new session. Global and per-IP limits need
  infrastructure in front of Streamlit (reverse proxy such as nginx `limit_req`, an API gateway, or a WAF).
  This is **not configured**.

## 6. Vector index: reliability and recovery

The index is **derived data**, built from `data/knowledge_base.json`. Losing it loses nothing.

| Situation | Behaviour |
|---|---|
| No index (first start, new container) | Built at startup (a few seconds) |
| KB, model or model revision changed | Fingerprint differs → rebuilt at startup |
| Index incomplete (chunk count wrong) | Rebuilt at startup |
| Index folder unreadable (corrupt SQLite) | Folder moved aside to `<CHROMA_DIR>.corrupt-<timestamp>` (kept for investigation, git-ignored) and rebuilt |
| Collection removed while the app runs | Rebuilt once on the next search. If that fails, users see "index not available" with a reference ID (`vector index unavailable` in the logs) |

**Manual recovery:** stop the app, delete or move the `CHROMA_DIR` folder, start the app.

**Streamlit Community Cloud:** the filesystem is ephemeral. The index (and the downloaded model) is rebuilt
after every restart or redeploy, which makes the first request after a restart slower. Nothing persistent is
stored, so this is safe. Do not rely on files written at runtime.

## 7. Routine tasks

| Task | How |
|---|---|
| Change the KB | Edit `data/knowledge_base.json` → `python -m src.kb_loader` (validator) → `python -m pytest -q` → restart (the index rebuilds automatically) |
| Rotate the OIDC client secret or cookie secret | Update the secrets → restart. A new cookie secret logs everyone out |
| Update the embedding model | Change `EMBEDDING_MODEL` / `EMBEDDING_MODEL_REVISION` → recalibrate → re-run the regression tests → restart |
| Investigate a user-reported error | Search the logs for the reference ID |

## 8. CI

`.github/workflows/ci.yml` runs on push and on pull requests:
1. installs CPU-only PyTorch and `requirements-dev.txt`, then runs `python -m pytest -q`;
2. builds the Docker image, starts it, waits for `/_stcore/health`, and runs `python -m src.health` inside
   the container.

**Status: prepared, not verified.** The workflow has not run on GitHub because nothing has been pushed. It
was checked locally only: the YAML parses, the requirements resolve, the CPU PyTorch wheel exists for
Linux/Python 3.12, and the same test command passes locally on Windows.

## 9. External dependencies not configured

| Dependency | Needed for | Status |
|---|---|---|
| OIDC provider (client ID/secret, redirect URI) | Real login when `AUTH_REQUIRED=true` | Not configured; only placeholders exist |
| Docker runtime | Building and running the image | Not available on the development machine; image not built |
| GitHub Actions runner | Running CI | Workflow prepared; never run |
| Log storage / monitoring / alerting | Keeping and searching logs, alerts | Not configured |
| Reverse proxy / gateway / WAF with TLS | HTTPS, global and per-IP rate limits | Not configured |
| Streamlit Community Cloud redeploy | Serving the Phase 2–4 code | Not done; live app unchanged |
