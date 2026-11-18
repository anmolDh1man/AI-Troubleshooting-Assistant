# Evaluation summary

Run: 2026-11-16 08:25 · Cases: `eval_cases.json` (33) · Tag: v1_phase3 · Generator: template (no LLM)

**Overall: 33/33 passed**

## Retrieval (in-KB cases, k=3)

- Hit@1: 20/20
- Hit@3: 20/20
- MRR@3: 1.0

## Decision zones (actual status by scope)

| Scope | answered | low_confidence | not_found | other |
|---|---|---|---|---|
| in_kb | 20 | 0 | 0 | 0 |
| out_of_kb | 0 | 3 | 6 | 0 |

- Confident answers to out-of-KB queries (hallucination risk): 0/9

## Pass rate by category

| Category | Passed |
|---|---|
| known_issue | 3/3 |
| paraphrase | 11/11 |
| paraphrase_hinglish | 1/1 |
| ambiguous | 2/2 |
| vague | 2/2 |
| unsupported_near_domain | 4/4 |
| unsupported_off_topic | 2/2 |
| prompt_injection | 1/1 |
| risky_action | 3/3 |
| invalid_input | 2/2 |
| generator_failure | 1/1 |
| retrieval_failure | 1/1 |

## Failures

None.
