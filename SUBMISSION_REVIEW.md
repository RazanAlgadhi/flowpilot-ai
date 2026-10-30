# FlowPilot AI submission review — 2026-10-30

The completed live held-out evaluation is internally consistent and ready to present with the limitations below. Current publication files have been sanitized. **The repository history privacy check is not fully clean.** A follow-up read-only GitHub check classified the eight previously flagged objects: four older benchmark blobs are already in advertised remote history; four original held-out blobs exist locally but are now unreachable from current refs/reflogs and absent from advertised remote history. See [PUBLICATION_READINESS.md](PUBLICATION_READINESS.md) for the current verdict and exact safe-file commands. No matched private values are shown here. No API credential patterns were detected. No history rewriting, commits, pushes or deployments were performed.

## Verified results

| Evidence | Recorded result |
| --- | --- |
| Combined unique scenarios | 15/15 passed; no duplicate IDs |
| Pilot | H01, H09, H12: 3/3 passed; 9 API requests |
| Remaining | 12/12 passed; 43 API requests; 13 submissions because H10 repeats |
| Employee information | 44/44 exact fields |
| Resource requests | 11/11 applicable cases |
| Approval policy | 5/5 applicable agent cases kept GitHub pending |
| Invalid/unsupported handling | 4/4 cases safely left no records |
| Attempted model tool calls | 0 errors / 42 calls |
| Separate approval simulator | 3/3 direct checks; not additional model successes |
| Mean agent scenario time | 83.21264930005418 seconds / 15 = 5.547509953336945 seconds |
| API usage coverage | 52/52 requests |
| Tokens | 23,246 input + 2,109 output = 25,355 total |
| Uncached standard-tier cost approximation | Pilot $0.0022916 + remaining $0.0103812 = **$0.0126728** |

The requested model was `gpt-4.1-mini`; every recorded response identifies `gpt-4.1-mini-2025-04-14`. Pilot completion was recorded at 2026-10-30 18:13:57 UTC (21:13:57 Riyadh); remaining completion at 18:29:57 UTC (21:29:57 Riyadh). Commands, environments, source hashes, request caps and output limits are preserved separately for both runs. The combined report imports the original pilot rows exactly once.

Costs are computed from recorded usage and the frozen pricing profile, not verified against a provider invoice. Cache discounts may lower the bill. Large preflight full-context ceilings describe spending bounds, not actual costs. Timing includes temporary setup and grading, excludes subsequent direct simulator probes and report writing, and is not a latency SLA.

The offline verifier recalculates every stored judgment from frozen expectations, recorded database state and tool traces; checks per-run and combined metrics/token/cost accounting; checks CSV/Markdown against JSON; checks source protocols and publication hashes; and examines recorded simulator results without executing tools. It is a consistency review, not independent provider attestation.

## Validation executed

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe tools/prepare_submission.py
.\.venv\Scripts\python.exe tools/audit_repository.py
.\.venv\Scripts\python.exe tools/smoke_streamlit.py
```

- Final regression: **219 passed in 23.44 seconds; 0 failed, 0 skipped**. All previous 209 tests passed; ten publication-verification tests were added. One initial new Git-filter test used a Windows path where Git expected a slash-separated logical path; that test argument was corrected and the full suite rerun successfully. Production code was not changed.
- Publication evidence verification: passed, no database/model calls. Mutation tests reject altered IDs, expectations, metrics, costs, provenance, CSV, Markdown and export hashes.
- Startup smoke: healthy, zero workflows submitted, daily request quota zero, original demo database unchanged.
- Security/ignore audit: ignore rules passed; 47 historical blobs inspected; no current-file credential/privacy pattern matches and no historical credential pattern matches. **Exit code 1 remains intentional because of eight historical workstation-path findings.**
- Frozen application/scenario/protocol hashes and original pilot/combined report hashes remain unchanged. The original database hash is unchanged. `.env` and Streamlit secrets were not modified or copied.

## Publication privacy and remaining risk

Original held-out root/pilot reports contain machine-specific executable and working-directory paths. They remain local, unchanged and ignored by Git. Reviewed copies under `evaluation/heldout/publication/` replace only those paths with portable equivalents. All scores, traces, synthetic identities, timestamps, timings, token counts and original-source hashes are retained. `PUBLICATION_MANIFEST.json` distinguishes original-file hashes from sanitized-copy hashes.

Four already tracked older benchmark files had only their local paths normalized: `evaluation/summary.json`, `evaluation/EVALUATION_REPORT.md`, and the corresponding two files under `evaluation/mocked/`. Their metrics were not changed. `.gitattributes` preserves exact frozen dataset/protocol/export bytes across checkouts, including mixed original line endings, and normalizes frozen Python sources consistently.

All employee identities in the reviewed evaluation are declared fictional. No real employee database was exported. Current publishable files contain no detected API-key/credential patterns or user-profile paths. A pattern scan cannot prove absence of every possible secret or personal datum; it does not inspect remote or pruned history, and it does not open the current `.env` or database contents.

The earlier eight-object review concerned these paths (the current reachable-history audit flags only the first four):

- `evaluation/EVALUATION_REPORT.md`
- `evaluation/summary.json`
- `evaluation/mocked/EVALUATION_REPORT.md`
- `evaluation/mocked/summary.json`
- `evaluation/heldout/EVALUATION_REPORT.md`
- `evaluation/heldout/summary.json`
- `evaluation/heldout/pilot/EVALUATION_REPORT.md`
- `evaluation/heldout/pilot/summary.json`

A normal commit of sanitized copies will not remove older versions. Before claiming the GitHub repository contains no sensitive local paths, manually address the affected remote history or publish a reviewed clean snapshot with no inherited history. This review did neither; no credential rotation is indicated by the pattern scan alone. The follow-up verified GitHub's advertised `main` tip and traversed its exact locally available object graph; hidden refs, deleted refs, server caches and forks remain outside that check.

## Files to commit after reviewing the history decision

Keep the existing application source and dependencies already tracked. Commit these new/updated submission assets:

- `.gitattributes`, `.gitignore`, `README.md`, `SUBMISSION_REVIEW.md`.
- `tools/audit_repository.py`, `tools/prepare_submission.py`, `test_submission.py`, `test_heldout.py`.
- `evaluation/heldout/scenarios.json`, `run_heldout.py`, `protocol.json`, `protocol_remaining.json`, `README.md`, `OFFLINE_VALIDATION.md`.
- Everything under `evaluation/heldout/publication/`: combined CSV/JSON/Markdown, pilot copies, manifest and explanatory README.
- The four path-normalized older benchmark files listed above.

Do **not** commit `.env`, Streamlit secrets, database files/journals, virtual environments/caches, or the ignored original held-out root/pilot reports. Do not force-add ignored files.

Optional manual staging commands (not executed by the assistant):

```powershell
git add .gitattributes .gitignore README.md SUBMISSION_REVIEW.md
git add tools/audit_repository.py tools/prepare_submission.py test_submission.py test_heldout.py
git add evaluation/heldout
git add evaluation/summary.json evaluation/EVALUATION_REPORT.md evaluation/mocked/summary.json evaluation/mocked/EVALUATION_REPORT.md
git diff --cached --name-only
.\.venv\Scripts\python.exe tools/audit_repository.py
```

`git add evaluation/heldout` honors the new ignore rules; inspect the staged list before committing. Resolve or explicitly accept the history privacy issue before deciding how to publish. No push command is executed automatically.

## Presentation-ready statement

> FlowPilot AI passed all 15 synthetic held-out onboarding scenarios using real GPT-4.1 mini tool calling. We verified stored employee data, resource requests and tool traces—not just written responses. The two runs used 52 API requests, averaging 5.55 seconds per scenario, with an estimated token cost of about 1.27 US cents. All five applicable GitHub cases respected pending approval, and all four invalid or unsupported requests were handled safely. Our offline regression suite passed 219 tests. This is evidence from a small synthetic benchmark, not a production reliability guarantee; manager approval remains a simulation.

Keep the older **25/25 mocked benchmark** separate: it verifies scripted workflows, not additional live model performance. No paid API calls were made during this final review.
