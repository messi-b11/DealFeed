# Verification — October 10, 2026

## Passed

- 17 Python API tests: full transaction and store reopening, six missing-field cases, past deadline, explicit approval, unresolved questions, cross-buyer/provider access, idempotent request creation, immutable proposals, recoverable inference failures, live mode refusing to silently use sample output, provider project posting, canonical relationships, invalid prices, asynchronous job ownership/completion/failure.
- TypeScript validation (`npm run typecheck`).
- Next.js 16.4 production static export, using Webpack. Turbopack production compilation failed on the local process/port sandbox boundary, including on retry; the supported Webpack compiler completed successfully.
- AWS template validation (`.venv/bin/cfn-lint infra/template.yaml`) with no findings. This is template validation, not an AWS deployment test.
- Dependency audit after updating Next.js: 0 known npm vulnerabilities at verification time.
- Browser rehearsal: missing fields produce inline clarification; selected Olive & Table project resolves to Studio North; buyer edits a generated sample brief; edit survives refresh; approval is required; request reaches Studio North; provider submits $4,500, scope, and timeline; buyer sees the proposal after refresh.
- Browser connected to the real local FastAPI/SQLite API: buyer request created and approved, provider proposal submitted, buyer proposal visible after refresh. No browser-rehearsal storage was used for that second transaction.
- Provider project posting in browser rehearsal: Harbor Cafe project appears in the feed and in Studio North’s profile after refresh.
- Profile exposes services, location, history, and explicitly illustrative contact information.
- 390px mobile feed and proposal views: no horizontal overflow; mobile navigation works.
- Browser console: no captured errors during the final UI checks.

Evidence: `docs/screenshots/buyer-proposal.png`, `docs/screenshots/mobile-feed.png`.

## Not verified / requires credentials

- Akamai inference: `scripts/check_inference.py` returned blocked with `AKAMAI_BASE_URL`, `AKAMAI_API_KEY`, and `AKAMAI_MODEL` missing. No live model request was made.
- Direct Akamai/Strands tool calling and Bedrock-orchestrated fallback: implemented, but cannot be validated without sponsor credentials and (for fallback) a Bedrock model.
- AWS account deployment, Lambda Linux container build, DynamoDB behavior in AWS, and S3 upload/download in AWS: credentials/CLI/Docker deployment environment were unavailable. Local API tests use SQLite.
- The published static rehearsal uses browser-local persistence. It is not a deployed AWS backend and cannot share transactions between devices.
- Sample provider sessions are deliberately switchable for the demo and are not production identity verification.

Run the post-deploy acceptance sequence in DEPLOYMENT.md once credentials are configured. Do not present the rehearsal template as live Akamai output.
