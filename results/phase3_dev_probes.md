# Phase 3 development probes: results

Probe file: `tests/dev_probes_phase3.json` (33 probes). It was written and fingerprinted before any Phase 3
functional change:
SHA-256 `926FCB0486B5AC4C913CEDDC9D16C6341AFEA731DE2AB5FC61F9C91CAB4E76EE` (recorded 2026-11-15, unchanged at the end of Phase 3).

These probes were used **during development** to guide and check the Phase 3 changes. They are therefore
**not an independent evaluation**. They were written by the same author as the implementation.

## Progress per change (probes meeting all of their expectations)

| After | Probes met | Fixed by this change |
|---|---|---|
| Before Phase 3 | 13/33 | - |
| Task 2: error-signature normalisation | 14/33 | P06 |
| Task 3: KB-013 database lock contention | 18/33 | P04, P07, P08, P09 |
| Task 4: rate-limit wording read as HTTP 429 | 19/33 | P12 |
| Task 5: "500s" duration guard + top-5 code re-rank pool | 20/33 | P16 |
| Task 6: risk detector (error text, informal cues, config changes) | 26/33 * | P19, P20, P21, P22 |
| Task 7: input checks (non-troubleshooting requests, event handlers, narrower "instructions") | 28/33 | P27, P28, P29, P30 |
| Task 8: negated symptoms removed from the retrieval text | 29/33 | P32 |
| Task 9: near-tie note in the possible-match zone (text only) | 29/33 | - |
| Completion fix A: error-signature re-rank (KB-derived), two re-rank-only signatures | **32/33** | P03, P23, P31 |
| Completion fix B: HTTP reason phrase in the search text | (33/33) | **rejected and reverted**, see below |

\* The Task 6 run started its suite after part of the Task 7 edits had been written, so P29 and P30 already
passed in that run. A clean run after Task 7 gave 28/33.

## Completion fixes for P03, P18, P23 and P31

| Probe | Before | Root cause | After |
|---|---|---|---|
| P03 `ECONNREFUSED when the settlement worker connects to the payments service` | **answered, KB-011 (confidently wrong)** | ECONNREFUSED was recognised, but "settlement worker" / "payments service" pulled the whole-sentence embedding to payment-flow entries; KB-007 was 3rd (0.499). Nothing used the fact that "connection refused" is in KB-007's own text. | answered, **KB-007** (0.499) |
| P23 `can we change the connection pool size on the payments service?` | possible match, KB-007, risk warning shown | "connection pool" was not treated as a database term; KB-003 was 2nd (0.305) behind KB-007 (0.319). | possible match, **KB-003** (0.305), risk warning still shown |
| P31 `the API isn't slow, it just refuses connections` | **answered, KB-004 (confidently wrong)** | The verb form "refuses connections" was not recognised as "connection refused"; after the negation was removed, generic "API" wording matched KB-004. KB-007 was 5th (0.416). | possible match, **KB-007** (0.416) |
| P18 `the refunds endpoint returns 504 after the deploy` | possible match, KB-001 | The query has the code but not its meaning; KB-002 (which mentions 504) scores 0.2968, below the 0.30 promotion floor. | **unchanged**: possible match, KB-001 (not fixed, see below) |

**Fix A (kept): error-signature re-rank.** Like the HTTP-code re-rank, an entry whose **own** embedded text
contains the query's error signature is moved to the front of the top-5 pool, if it scores at least 0.30. Which
entry carries which signature is derived from the KB text by the same patterns (KB-003: connection refused and
connection pool; KB-007: connection refused and DNS errors; KB-013: locks), not hand-mapped. Scores are not
changed by the re-rank. "refuses connections" and "connection pool" were added as **re-rank-only**
signatures: they append no text to the search. An earlier variant that also appended a phrase for them made
P31 and an off-topic query ("the venue refused all connections to the guest wifi") confident answers, so the
phrase was dropped.

**Fix B (rejected and reverted): HTTP reason phrase.** Appending "HTTP 504 Gateway Timeout" etc. to the search
text fixed P18 (33/33) without failing any V1/V2 case, but it raised the score of every query that names a
covered code. In a safety check, off-topic queries became confident answers: "our marketing blog returns
500 since the theme update", "the office printer shows error 500 pages remaining" (both KB-001) and
"the weather widget on the intranet returns 504" (KB-002). Before the change they were possible matches. That
is a safety regression, so the change was reverted. The 0.30 floor was not lowered.

## Final state (32/33)

| Probe | Status | Top entry | Result |
|---|---|---|---|
| All except P18 | as expected | as expected | met |
| P18 `the refunds endpoint returns 504 after the deploy` | possible match | KB-001 (expected KB-002) | **not met**: shown as a cautious possible match with a warning and clarifying questions, not as a confident answer |

P18 is the only known failure in `tests/test_eval_regression.py`. Any other probe that starts failing fails the
test suite. V1 and V2 results did not change in any compared column (status, top entry, score, pass/fail, risk
warning) through the completion fixes, so `results/eval_results_v1_phase3.csv` and
`results/eval_results_v2_phase3.csv` still describe the final code.
