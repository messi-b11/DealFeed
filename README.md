# DealFeed

Find completed work you like, describe what you need, and choose a provider with evidence. DealFeed connects community project discovery to business matching, selected invitations, independent provider proposals, and an explicit customer decision.

The connected marketplace supports:

- One inspiration project, optional saved references, editable requirements, budget, deliverables, keywords, must-haves, and confirmed style preferences.
- Up to five distinct businesses, with requirement assessments, comparable completed work, sourced achievements, website evidence, gaps, and unknowns. Confirmed mandatory conflicts exclude a business; fewer suitable businesses are explained.
- Business exploration without invitations, followed by explicit recipient selection and approval of one frozen shared brief.
- A parent Deal with one to five provider invitations, atomic and idempotent approval, provider-scoped responses, and persistent buyer tracking.
- Provider-authored fit statements, approach, portfolio references, deliverable coverage, exclusions, assumptions, price, and timeline.
- Evidence-supported offer comparison, price differences calculated in code, and a customer-recorded preferred provider. This preference makes no payment or contractual acceptance.

The restaurant website example has sample portfolio coverage for five suitable businesses. Catering, event decorations, and keynote speaking remain available. Existing single-provider requests, proposals, and completed-project posting are preserved.

## Run the connected product

Install dependencies once:

```sh
npm ci
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
```

Copy `.env.example` to an ignored `.env.local` and supply your configuration there. Keep credentials out of source control and `NEXT_PUBLIC_*` variables.

| Setting | Purpose |
| --- | --- |
| `AKAMAI_BASE_URL` | Organizer-provided OpenAI-compatible inference endpoint |
| `AKAMAI_API_KEY` | Server-only inference credential |
| `AKAMAI_MODEL` | Model identifier supported by that endpoint |
| `AI_MODE` | Select `live` for actual inference or `rehearsal` for explicitly labeled deterministic analysis |
| `STRANDS_MODEL_MODE` | `direct` for Akamai orchestration; `tool` for a configured Bedrock orchestrator with Akamai analysis |
| `BEDROCK_MODEL_ID`, `AWS_REGION` | Needed for the optional Bedrock orchestration path |
| `SESSION_SECRET` | Optional persistent local demo signing secret; the launcher creates one when absent |
| `DEALFEED_PORT`, `DEALFEED_API_PORT` | Optional frontend and API port overrides |

`.env.example` selects rehearsal. Change `AI_MODE` explicitly before demonstrating live inference; configured credentials alone do not change that setting. The launcher reads the local environment files and retains the selected mode.

```sh
npm run dev:connected
```

Open [http://127.0.0.1:3001](http://127.0.0.1:3001). This starts Next.js and FastAPI, persists data in `.local/dealfeed.sqlite`, enables asynchronous analysis jobs, and connects the browser through the same-origin `/api` development proxy. The API listens on `127.0.0.1:8000`. The launcher sets `NEXT_PUBLIC_API_URL`, `DEALFEED_API_ORIGIN`, `ALLOWED_ORIGIN`, and the local database path; manual CORS configuration is unnecessary for this command. Ctrl+C stops both services.

Analysis runs asynchronously and the UI polls for the result. The inference orchestration deadline is 120 seconds, so allow up to two minutes for a slow run plus polling/network overhead. It is not a guaranteed response time. Failed analysis preserves the criteria or received proposals and surfaces a recoverable error; live requests never silently become rehearsal output.

For a known deterministic connected rehearsal, use `npm run dev:local`. This deliberately forces rehearsal and strips inference settings. The full matching, invitation, provider-response, and selection workflow still uses the persistent local API, but its analysis is labeled **Rehearsal analysis · No live AI**.

For the legacy frontend-only browser rehearsal, start `npm run dev` with no `NEXT_PUBLIC_API_URL`. Its single-provider drafts, requests, and proposals persist only in that browser. Five-business matching explains that it requires the connected API.

## How to try the full journey

1. Open a completed website project and select **Request something similar**.
2. Use **Use restaurant demo requirements**, review or edit the criteria, confirm preferences, and select **Find suitable businesses**.
3. Inspect the five candidates. Expand **Requirement alignment & questions** and **Supporting sources**, or select **Explore business**. Exploration sends nothing.
4. Select one or more recipients, open **Review invitation**, review the exact shared brief, tick approval, and send.
5. Open **Provider workspace** and switch to an invited sample business. Fill its own request with a fit statement, approach, evidence, coverage, price, scope, and timeline. Review and send the proposal; repeat for other invited businesses as desired.
6. In **My deals**, refresh the deal and select **Analyze responses**. Inspect the raw responses alongside analysis. Select a business, choose it, and explicitly confirm the preferred provider. Refresh to verify persistence.

A presentation-ready walkthrough, prepared sample responses, and timing guidance are in [docs/DEMO.md](docs/DEMO.md).

## Evidence and analysis modes

The Strands SDK orchestrates bounded retrieval, website research, validated matching, and proposal analysis. In live mode, Akamai inference influences business ordering and supported semantic insights. Deterministic code enforces eligibility, source ownership, schema validation, and monetary arithmetic. AI interpretations are labeled as inferences and expose supporting excerpts.

The supplied businesses, projects, prices, and achievements are illustrative sample data. Their `.example` websites are never fetched: the UI identifies website fixtures and their recorded dates. Real public-site research is bounded, cached, source-attributed, and restricted against private destinations and unsafe redirects. A business's own website remains a company-reported source; fetching it does not independently verify its claims. Portfolio styling tags are metadata, not image analysis.

The UI distinguishes **Live AI · Akamai + Strands** from rehearsal analysis. Sample business evidence can be analyzed by live AI; those are separate properties. A successful health check or credentials check is not evidence of a completed inference run. Consult [docs/VERIFICATION.md](docs/VERIFICATION.md) for the exact tested modes and deployment status.

## Architecture and persistence

- Next.js 16 / React frontend with a static production export and responsive shortlist and comparison views.
- FastAPI API with signed, role-scoped demo sessions; SQLite locally and an existing DynamoDB adapter for AWS.
- Canonical catalog and evidence records, persisted match runs, frozen Deals, provider-specific child Requests, immutable proposals, and versioned comparisons.
- Atomic invitation fan-out and payload-bound idempotency. Comparison fingerprints invalidate stale analysis when its inputs change.
- A single bounded Strands orchestrator; research and analysis tools cannot invite businesses or select a provider.
- The provider inbox reuses the existing request flow and never exposes competitors' private proposals.

Contracts: [docs/CONTRACT.md](docs/CONTRACT.md) and [docs/API.md](docs/API.md). Implementation rationale: [docs/BLUEPRINT.md](docs/BLUEPRINT.md). Deployment details: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Verify and preview a production export

```sh
.venv/bin/python -m pytest backend/tests -q
npx tsc --noEmit
npm run build
```

With the connected API already running, the API rehearsal creates explicitly fictional records and checks matching, invitation idempotency, provider isolation, comparison, and persistent choice:

```sh
.venv/bin/python -m scripts.rehearse_marketplace --api http://127.0.0.1:8000
```

This script creates its own buyer session; its records are not automatically attached to the browser's buyer identity. Its reported mode is the API's actual mode. `scripts/evaluate_matches.py` provides the fixed matching evaluation. These commands describe checks to run; current results are recorded in [docs/VERIFICATION.md](docs/VERIFICATION.md).

For a production build served with the persistent API on one origin, build with `NEXT_PUBLIC_API_URL=/api`, then run `scripts/serve_app.py` with the required server environment. Its frontend comes from `out/`, and its API is mounted at `/api`. `npm start` serves only the static export and does not start an API. A static export built with `/api` needs that API mount or a hosting proxy; simply publishing static files does not deploy the backend. Changes to `NEXT_PUBLIC_API_URL` require a frontend rebuild.

## Demo boundary

Signed sessions enforce record scoping, but selectable sample identities are **demo authentication**, not verified buyer identity or provider membership. Use fictional customer details. Public commercial operation requires real authentication, verified membership, and operational controls. Payments, contracts, messaging, autonomous negotiation, and broad web crawling are outside this build.

Dependencies are locked with `package-lock.json` and `backend/requirements.lock.txt`. Revalidate platform-specific Python dependencies in the chosen deployment runtime.
