# Individual contribution and use of AI tools

This project was built by me (Anmol Dhiman) with **Claude Code** (Anthropic's coding assistant, model Claude Opus 5.5) as an AI pair programmer. This document states clearly which decisions and work were mine and where the AI tool was used.

## My contribution

**Requirements and constraints**
- Selected the case study and wrote the working brief for the AI assistant:
  - extract every requirement from the assignment and JD
  - map requirements to implementation
  - separate mandatory from optional work
  - avoid invented requirements, fabricated data and unverified claims
- Set the technical constraints:
  - no paid API keys
  - Streamlit UI
  - local embedding model
  - ChromaDB for retrieval, only if it proved reliable
  - a transparent, non-LLM answer generator that never presents itself as LLM output
  - a modular design so an LLM can be added later

**Decisions during development**
- Approved the architecture and the phased plan (MVP first) before any code was written.
- Asked for the Streamlit startup error to be investigated without blindly changing constants or decision logic. This led to finding that Windows Smart App Control was blocking files.
- Decided to fix the E04 retrieval gap under strict rules:
  - inspect the schema first
  - don't change thresholds
  - add a new regression test
  - don't overwrite the committed baseline results
  - report the before/after comparison honestly

**Hands-on work**
- Set up the environment: installed Python 3.12 with the Python Install Manager, created and activated the virtual environment, installed dependencies, and initialised Git.
- Ran verification commands and committed the work phase by phase.
- Ran the application locally, which surfaced the Smart App Control startup problem.

## Where AI tools were used

**Claude Code (Claude Opus 5.5)**
- Analysed the assignment and JD.
- Proposed the architecture, tech stack and phased plan.
- Wrote the source code, the sample knowledge-base content, the tests, the calibration and evaluation scripts, and the documentation drafts.
- Ran tests and evaluations in my local environment and reported the results, including failures.
- Diagnosed environment problems: the Python 3.14 / Anaconda conflict and the Smart App Control blocks.

**Retrieval model (inside the application):** `sentence-transformers/all-MiniLM-L6-v2`, a pre-trained open-source embedding model, run locally.

**Not used:** no LLM API is called by the application. Answers are produced by a rule-based template from the retrieved knowledge-base entry and are labelled as such in the UI.

## Upgrade work (Phases 1–4, branch `upgrade/phase-1`)

After the original version, the project was upgraded in four phases with the same AI pair-programming setup.

**My decisions**
- Required a read-only audit and an explicit plan before each phase. I approved phases one at a time and allowed no extra sub-phases.
- Set the evaluation rules:
  - write a sealed V3 set before Phase 2, run it exactly once with pre-registered pass/fail criteria, and never use it for tuning;
  - keep the V3 data private;
  - never change thresholds or weaken tests and regression gates to improve scores;
  - revert any change that causes a regression;
  - report failures and limitations honestly; never fabricate results or claim independent validation.
- Chose specific behaviours:
  - input that mixes a prompt injection with a real question is rejected as a whole;
  - a probe that could not be fixed safely (P18) stays a cautious possible match instead of being forced to pass;
  - optional login must fail closed;
  - a malformed secrets file must stop the app instead of silently disabling a required login.
- Approved the production-readiness scope (Phase 4) and a final pre-GitHub audit. Decided not to rewrite published history.

**Where Claude Code was used**
- Implemented each phase:
  - Phase 1: evaluation metrics and a regression gate;
  - Phase 2: risk detection, input safety and HTTP-code matching;
  - Phase 3: retrieval and safety improvements;
  - Phase 4: configuration validation, safe errors, logging, rate limiting, health checks, optional OIDC login, Dockerfile, CI workflow and documentation.
- Ran the tests and evaluations, and reported every regression and rejected change. For example, it rejected and reverted a retrieval change that made unrelated queries confident.

## How AI-generated work was checked

- The original version was verified by running each phase locally before committing: setup check, KB validation, retrieval calibration, unit tests, CLI runs, UI tests and the held-out evaluation.
- In the upgrade, every change was checked locally before review. The checks were:
  - the full automated test suite;
  - a per-case comparison of the V1 and V2 evaluation sets against the previous results;
  - the development probes, the calibration queries and the E04 regression test;
  - for Phase 4, a live smoke test of the running app and its logs.
- Thresholds were set from measured score distributions and then checked on a separate held-out set. All results, including failures, are reported as measured.
- Evaluation and calibration results quoted in the README come from actual runs saved in `results/`. Automated test counts in the README come from the latest full test run; they are not saved as files.
- Not verified: the Docker image has not been built (Docker was not available), and the CI workflow has not run on GitHub. No independent (V4) evaluation has been done.

## My Additional Contributions

- Reviewed the AI-generated code and documentation for accuracy.
- Ran the application locally and verified its behavior using sample troubleshooting queries.
- Executed the automated test suite and reviewed the test results.
- Reviewed the retrieval evaluation results and verified the targeted E04 fix.
- Prepared the project demonstration and interview explanations.
