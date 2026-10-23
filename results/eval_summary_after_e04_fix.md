# Evaluation summary

Run: 2026-10-23 11:50 · Tag: after_e04_fix · Cases: 33 · Generator: template (no LLM)

**Overall: 32/33 passed**

- Retrieval top-1 accuracy on in-KB queries: 15/15
- Out-of-KB / vague queries NOT answered confidently: 9/9
- Confident answers to out-of-KB queries (hallucination risk): 0

| Category | Passed |
|---|---|
| known_issue | 3/3 |
| paraphrase | 11/11 |
| paraphrase_hinglish | 1/1 |
| ambiguous | 2/2 |
| vague | 2/2 |
| unsupported_near_domain | 4/4 |
| unsupported_off_topic | 1/2 |
| prompt_injection | 1/1 |
| risky_action | 3/3 |
| invalid_input | 2/2 |
| generator_failure | 1/1 |
| retrieval_failure | 1/1 |

## Failures

- **E25** (unsupported_off_topic) `Write me a poem about servers`: status=low_confidence, expected ['not_found']
