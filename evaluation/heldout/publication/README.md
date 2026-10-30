# Reviewed publication evidence

These are sanitized copies of the completed live evaluation: **15/15 cases passed, 52 API requests**. The original pilot (3 cases, 9 requests) and remaining run (12 cases, 43 requests) are combined exactly once. No additional live calls were made to prepare these files.

- `summary.json`: all scenario evidence, exact metrics, model metadata and both run histories.
- `results.csv`: one row per scenario.
- `EVALUATION_REPORT.md`: methodology, metrics, case results, costs and limitations.
- `pilot/`: sanitized original pilot evidence.
- `PUBLICATION_MANIFEST.json`: original and sanitized-file SHA-256 hashes.

Only local workstation paths were normalized to `.` or repository-relative commands. Expected answers, scenario decisions, traces, timestamps, timings, token counts, costs and source hashes were not changed. Original pilot hash references inside the combined report deliberately identify the private original files. They differ from the public-copy hashes in the manifest.

From the repository root, run `python tools/prepare_submission.py` for read-only offline verification. It recomputes judgments and metrics, verifies CSV/Markdown consistency, checks both source protocols and validates export hashes. It does not require the ignored original reports, credentials or API calls. `--prepare` is only for regenerating these exports from the retained local originals.

This establishes consistency of recorded evidence, not an independent provider audit or cryptographic attestation. Cost is an uncached token-price estimate, not an invoice. All employee identities are synthetic. The 15 purposively constructed cases do not establish broad production reliability; the approval simulator is unauthenticated and does not provision resources.
