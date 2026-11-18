# Evaluation summary

Run: 2026-11-13 21:30 · Cases: `eval_cases_v2.json` (44) · Tag: v2_phase2b · Generator: template (no LLM)

**Overall: 37/44 passed**

## Retrieval (in-KB cases, k=3)

- Hit@1: 23/28
- Hit@3: 26/28
- MRR@3: 0.869

## Decision zones (actual status by scope)

| Scope | answered | low_confidence | not_found | other |
|---|---|---|---|---|
| in_kb | 17 | 9 | 2 | 0 |
| out_of_kb | 1 | 5 | 8 | 0 |

- Confident answers to out-of-KB queries (hallucination risk): 1/14

## Pass rate by category

| Category | Passed |
|---|---|
| jargon | 6/9 |
| typo | 3/4 |
| hinglish | 4/4 |
| multi_issue | 2/2 |
| negation | 0/1 |
| short | 0/1 |
| noisy | 1/1 |
| near_domain | 7/8 |
| off_topic | 4/4 |
| prompt_injection | 2/2 |
| risky_action | 3/3 |
| risk_false_alarm | 3/3 |
| invalid_input | 2/2 |

## Failures

- **V02** (jargon) `FATAL: sorry, too many clients already`: source=['KB-001'], expected one of ['KB-003']
- **V03** (jargon) `connect ECONNREFUSED 10.0.3.15:5432`: status=not_found, expected ['answered', 'low_confidence']
- **V07** (jargon) `SERVFAIL when resolving api.bank.example`: source=['KB-001'], expected one of ['KB-007']
- **V13** (typo) `dsik ful on app servr`: status=not_found, expected ['answered', 'low_confidence']
- **V20** (negation) `the API is not slow, it fails immediately with 503`: source=['KB-005'], expected one of ['KB-006']
- **V21** (short) `504s`: source=['KB-006'], expected one of ['KB-002']
- **V23** (near_domain) `HTTP 429 too many requests from the partner API`: status=answered, expected ['not_found', 'low_confidence']; gave a confident answer for an issue that is not in the KB
