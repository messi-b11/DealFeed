# DealFeed API v1

All writes use JSON. Dates are ISO 8601; budgets are buyer preferences, prices are provider-authored USD amounts. API responses never trust a caller-supplied businessId or buyerId: relationships are resolved from stored records. Error envelope: `{ "error": { "code": "...", "message": "...", "fields": {} } }`.

| Method | Path | Input / output |
|---|---|---|
| GET | /health | mode, storage, integration configuration status (no secrets) |
| POST | /sessions | `{role: "buyer" | "provider", businessId?: string, buyerId?: string}` → signed sample actor token; demo-only |
| GET | /projects | `{projects: Project[], businesses: Business[]}` |
| GET | /businesses/{id} | `{business: Business, projects: Project[]}` |
| POST | /projects | provider only: title, client, description, category, result, image → Project |
| POST | /uploads | provider only: contentType → private S3 PUT URL and image key |
| POST | /briefs | BuyerInput → Draft; 422 for missing fields; 503 for retryable inference errors |
| GET | /briefs/{id} | AWS async mode: `{status: "pending"}` or `{status: "complete", draft: Draft}`; owner scoped |
| POST | /requests | `{draftId, approved: true, brief: Brief}` → Request; idempotent by draftId |
| GET | /requests | Requests owned by authenticated buyer, or addressed to authenticated provider |
| POST | /requests/{id}/proposal | ProposalInput → Proposal; one immutable proposal per request, conflict on repeat |

Bearer sample sessions establish actor ownership. Provider sessions are deliberately selectable in the hackathon demo; these are not production provider identity verification. Deployment requires DEMO_AUTH_ENABLED=true until a real identity provider is implemented. Never use real customer information in this sample deployment.

`Brief = {title, summary, deliverables: string[], questions: string[], constraints: string[], reference}`. `Draft = {id, projectId, businessId, buyerId, input, brief, mode, trace, createdAt}`. `Request = Draft & {status, approvedAt, proposal?}`. `Proposal = {id, requestId, businessId, buyerId, price, currency, scope, timeline, createdAt}`. Full client types are in lib/types.ts; server validation is in backend/models.py.

No request is saved by brief generation. Only an explicit approved submission can invoke save_request. Missing information blocks generation; unresolved AI questions block approval. Live failures never silently fall back to sample output.

On Lambda, POST /briefs returns HTTP 202 `{jobId, status: "pending"}` and schedules asynchronous generation. The client polls GET /briefs/{jobId}. Locally it returns the Draft synchronously. A failed or stale job returns a recoverable 503. Only the AWS backend uses DynamoDB/S3; the local API uses SQLite and the disconnected frontend uses clearly labeled browser storage.
