# R11 Failures Report

## Summary

**ZERO FAILURES** — All 5 questions completed successfully.

| Metric | Value |
|--------|-------|
| Questions attempted | 5 |
| Questions succeeded | 5 |
| Questions failed | 0 |
| Vector retrieval failures | 0 |
| Graph retrieval failures | 0 |
| Answer generation failures | 0 |
| Timeout failures | 0 (Q5 initial timeout was retried successfully) |
| Evaluation failures | 0 |

## Notes

- Q5 initially timed out at 300s due to long answer generation (5000 tokens, 73s generation time).
  Retried with extended Bedrock read_timeout=600s and completed successfully.
- All other questions completed within default timeouts.
