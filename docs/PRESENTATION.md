# 10-Minute Presentation Plan

Total: 10:00 for presentation and demo, then 5–10 minutes of Q&A.
Rule of thumb: about 1 slide per minute; the demo gets the most time.

| # | Slide | Time | Cumulative |
|---|---|---|---|
| 1 | Title and problem | 0:30 | 0:30 |
| 2 | Requirements and what I built | 0:45 | 1:15 |
| 3 | Architecture and data flow | 1:15 | 2:30 |
| 4 | Knowledge-base design | 0:45 | 3:15 |
| 5 | Retrieval: how it finds the right entry | 1:15 | 4:30 |
| 6 | Handling the unknown, and safety | 1:00 | 5:30 |
| 7 | Live demo | 2:15 | 7:45 |
| 8 | Testing and evaluation results | 1:00 | 8:45 |
| 9 | Limitations and next steps | 0:45 | 9:30 |
| 10 | My contribution and AI tools; close | 0:30 | 10:00 |

---

## Slide 1: Title and problem (0:30)
**On slide:** "AI Troubleshooting Assistant for L1/L2 Support"; your name; one sentence on the problem.

**Say:**
> "L1 and L2 engineers spend a lot of time searching runbooks for the same recurring issues. I built an assistant that takes a plain-language problem description, finds the matching knowledge-base entry, and gives step-by-step checks and the right escalation team, always showing the source. Just as important, when it doesn't know, it says so."

## Slide 2: Requirements and what I built (0:45)
**On slide:** the six assignment requirements with a ✅ each:
- small KB
- chat interface
- retrieval
- AI-formulated response
- steps and escalation
- source shown
- handles unknown issues

Add one honest line: "Response formulation: template from the KB, no LLM (no paid API available), with a pluggable generator."

**Say:**
> "Every requirement is covered. One honest note: I had no paid LLM API, so AI is used for understanding and retrieving. The answer itself is built transparently from the retrieved entry and labelled 'no LLM'. The generator is a separate component, so an LLM can be plugged in later."

## Slide 3: Architecture and data flow (1:15)
**On slide:** the flow diagram from the README: query → validation → retriever (MiniLM + ChromaDB) → decision gate (three zones) → template generator → UI with source.

**Say:**
> "Four small modules, each with one job:
> - The **loader** validates the knowledge base.
> - The **retriever** turns text into embeddings and searches ChromaDB. It only ranks; it never decides.
> - The **assistant** makes the decisions: is the match good enough, is it ambiguous, does the question mention a risky action.
> - The **generator** writes the answer.
>
> The UI only displays results. Because of this separation, I can test the decision logic with a fake retriever, and swap the generator for an LLM without touching anything else."

## Slide 4: Knowledge-base design (0:45)
**On slide:** a trimmed KB-003 entry. Highlight `symptoms`, `diagnostic_checks`, `requires_approval`, `escalation`.

**Say:**
> "12 sample entries covering common payment-platform issues: 500s, timeouts, database pools, auth, TLS, card declines, settlement jobs. Each has symptoms, read-only checks, safe next steps, and escalation rules with conditions. Disruptive actions such as restarts or rollbacks live in a separate 'requires approval' list, so they're never shown as normal steps. The loader validates every entry, including the allowed team names, so bad data can't reach the UI. All of this is simulated sample data."

## Slide 5: Retrieval (1:15)
**On slide:** the before/after calibration table:

| | One vector per entry | One vector per symptom |
|---|---|---|
| Lowest correct match | 0.384 | 0.483 |
| Highest out-of-KB | 0.386 ❌ | 0.415 ✅ |

**Say:**
> "Each text becomes a 384-number vector, and similar meanings give vectors pointing the same way. I measure that with cosine similarity.
>
> My first version embedded each entry as one long text. When I measured it, an unrelated query, Kafka lag, scored higher than a correct match. The long text diluted the meaning. So I embedded each symptom separately and scored each entry by its best-matching symptom. On the same queries, correct and unrelated scores became separable.
>
> I chose the thresholds from this data, not by guessing."

## Slide 6: Handling the unknown, and safety (1:00)
**On slide:** three coloured zones (green ≥ 0.45 answered · yellow 0.30–0.45 possible match · blue < 0.30 not found), plus the safety bullets.

**Say:**
> "The assistant doesn't always answer:
> - **Below 0.30:** it says the knowledge base doesn't cover the issue and asks for the service, the error code, and when it started. It suggests no fix.
> - **In the middle:** it shows the closest entry with a clear 'possible match' warning.
>
> For safety, it can't execute anything. Risky actions are marked as requiring approval, and if your question mentions restarting or deleting something, you get an explicit warning."

## Slide 7: Live demo (2:15). See the demo script below.

## Slide 8: Testing and evaluation (1:00)
**On slide:**
- 33 automated tests passing
- Held-out evaluation: **31/33 baseline → 32/33** after one targeted fix
- **0** confident answers to out-of-KB questions
- **0** grounding or attribution violations

**Say:**
> "I tuned on one query set and evaluated on a separate one I wrote beforehand, so I wasn't grading my own homework. The key result: zero confident answers to questions outside the knowledge base.
>
> There were two failures:
> - A HikariCP pool-timeout query matched the timeout entry instead of the database entry. I fixed it with keywords and a regression test, without changing thresholds. Since I fixed it after seeing it, the clean figure is 31/33.
> - 'Write me a poem about servers' got a cautious 'possible match' instead of 'not found'. I left that documented."

## Slide 9: Limitations and next steps (0:45)
**On slide:** three limitations and three next steps.
- **Limitations:** no LLM wording; small KB and small test sets; ambiguity detection only compares scores.
- **Next steps:** optional LLM with citation checks; hybrid keyword + vector search; a KB built from real incident tickets with a feedback loop.

**Say:**
> "It's a prototype. Answers can't adapt to specific details, the KB and test sets are small, and something like 'payments are failing' should get a follow-up question but currently doesn't. The next steps are an LLM that's only allowed to use retrieved entries and must cite them, hybrid search for jargon, and growing the KB from real incidents."

## Slide 10: My contribution and AI tools; close (0:30)
**Say:**
> "I defined the requirements and constraints, made the design decisions, including no fake LLM output and how to fix the evaluation failure, set up and ran everything, and verified each phase. I used Claude Code as an AI pair programmer for code, KB content and documentation drafts; the details are in CONTRIBUTION.md. Thank you, happy to take questions."

---

# Live demo script (2:15)

## Before the session (10 minutes before)
1. Activate the venv and run `python -m streamlit run app.py`.
2. **Warm up:** run one query so the model is loaded, then click **Clear chat**.
3. Zoom the browser to about 125% so the audience can read it. Close other apps and notifications.
4. Have the **backup recording** open in another window.
5. Fallback if the UI fails: `python -m src.assistant "The payment API is returning a 500 error"` in the terminal.

## Queries (each one verified on the development machine)

| # | Query | Expected | What to point at |
|---|---|---|---|
| 1 | `The payment API is returning a 500 error` (sidebar button) | 🟢 KB-001, 0.86 | The assignment's own example. Numbered checks → yellow **Requires approval** box → escalation teams → open **📄 Source used** and show the raw entry → caption **"Generated by: Knowledge-base template (no LLM)"**. |
| 2 | Type: `Customer paid but the merchant never received the callback` | 🟢 KB-011, 0.73 | "I didn't use words like 'webhook' or 'pending', but it found the right entry. That's semantic search." Show the "Best-matching text" in the source panel. |
| 3 | `Should I restart the production database? App says too many connections` (sidebar) | 🟢 KB-003 plus 🔴 warning | The red risky-action warning, and that restarting appears only under "Requires approval". |
| 4 | `Kafka consumer lag is increasing` (sidebar) | 🟡 possible match, 0.42 | "Not in my KB. It doesn't pretend: it shows a yellow warning and asks clarifying questions." |
| 5 | `My laptop keyboard is not working` (sidebar) | 🔵 not found | "No steps and no source. It refuses to invent a fix." |

**Closing line:** "So the assistant answers when it can, is cautious when unsure, and refuses when it doesn't know, and every answer shows where it came from."

If time is short, skip query 2.
