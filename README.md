# DealFeed

A focused website-design marketplace: completed work → buyer request → reviewed brief → provider proposal.

## Run locally

```sh
npm ci
npm run dev
```

Open the printed URL. With no `NEXT_PUBLIC_API_URL`, the app runs in explicitly labeled browser rehearsal mode: sample businesses, deterministic sample briefs, browser-local drafts/requests/proposals. This mode does **not** call Akamai or pretend to be AI. Data persists across refreshes on the same origin/browser; it is not shared across devices.

For the persistent API:

```sh
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
AI_MODE=rehearsal DEMO_AUTH_ENABLED=true ALLOWED_ORIGIN=http://127.0.0.1:3001 .venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

In a second terminal, start the frontend with `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000 npm run dev -- --port 3001`. The API stores records in `.local/dealfeed.sqlite`. Exact frontend origin must match `ALLOWED_ORIGIN`. The frontend environment variable is compiled into the app; restart development or rebuild after changing it.

## Sponsor integration: first check

Credentials were not present during implementation. Live Akamai inference and AWS deployment are **not verified**. No endpoint or model ID is guessed.

Configure `AKAMAI_BASE_URL`, `AKAMAI_API_KEY`, and `AKAMAI_MODEL` in the process environment or an ignored `.env.local`. The endpoint must support the OpenAI-compatible chat completions API. Run:

```sh
.venv/bin/python -m scripts.check_inference
```

The check first runs a real Strands `OpenAIModel` against Akamai and verifies a tool invocation. It then exercises project retrieval, business retrieval, and schema-validated Akamai brief generation. If direct tool calling fails, configure AWS credentials and `BEDROCK_MODEL_ID`; the check retries with a supported Strands Bedrock model coordinating `generate_brief`, which still calls Akamai. The JSON result reports the verified `STRANDS_MODEL_MODE`. No fake success, silent sample fallback, credentials, or raw provider responses are printed.

For the live API set `AI_MODE=live`, `STRANDS_MODEL_MODE=direct` (or the verified `tool` fallback), and the same Akamai settings. Use `uvicorn --env-file .env.local` to load a configuration file. Live inference errors are recoverable 503 responses, and entered requirements remain in the browser.

Implementation follows the official [Strands OpenAI-compatible model provider](https://strandsagents.com/docs/user-guide/sdk/model-providers/openai/) and [Bedrock model provider](https://strandsagents.com/docs/user-guide/sdk/model-providers/amazon-bedrock/) contracts. Sponsor-specific endpoint compatibility still requires the check above.

## Architecture

- Next.js 16 + React + Tailwind 4; static export works with Sites, S3/CloudFront, or another static host.
- API Gateway HTTP API → Python Lambda via FastAPI/Mangum.
- DynamoDB records for businesses, projects, drafts, jobs, requests, proposals. SQLite uses the same repository interface locally.
- Private S3 bucket stores provider-uploaded project images; API returns expiring read URLs. Seed sample artwork is bundled SVG. Upload UI accepts JPG/PNG/WebP up to 2 MB.
- AWS brief generation is asynchronous: POST returns a job, Lambda runs the Strands flow, frontend polls the owner-scoped status endpoint. This avoids API Gateway’s synchronous timeout.
- `get_project` and `get_business` enforce the selected relationships. `generate_brief` ignores model-supplied replacements and uses canonical buyer input and retrieved records.
- `save_request` is a Strands-decorated tool invoked deterministically only after explicit buyer approval. It is never exposed to the drafting agent. This keeps the model from approving its own output.
- Providers supply all proposal pricing, scope, and timelines. One immutable proposal per request; duplicate request approval is idempotent.

API contracts: [docs/API.md](docs/API.md). Deployment: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). Rehearsal: [docs/DEMO.md](docs/DEMO.md).

## Verify

```sh
.venv/bin/python -m pytest backend/tests -q
npm run typecheck
npm run build
```

Tests cover missing details, explicit approval, canonical ownership, cross-buyer/provider isolation, duplicate submissions, provider-authored pricing, persistence, project posting, async job ownership, and inference failure/retry. Browser QA and its known limits are recorded in [docs/VERIFICATION.md](docs/VERIFICATION.md).

## Demo boundary

The sample workspace intentionally lets the presenter switch between sample providers. Signed sessions enforce record scoping, but `/sessions` is a **demo role switch, not production identity verification**. Do not enter real customer information. A production rollout requires real buyer identity and verified provider membership; `DEMO_AUTH_ENABLED=false` fails closed until that exists. Payment, messaging, recommendations, calendars, and invoices are deliberately absent.

Dependencies are locked with `package-lock.json` and `backend/requirements.lock.txt`. Python's lock snapshot was produced on macOS/Python 3.14; Lambda uses a Linux/Python 3.13 container build from the bounded requirements file. Recheck the native dependencies in that deployment build.
