# Marketplace API contract

All protected routes use the existing bearer demo session. Buyer identity owns match runs and deals. Provider identity owns only its child requests and proposals. Monetary input uses integer cents for criteria; proposals retain decimal `price` and `currency` for legacy compatibility.

## Criteria and matching

`POST /matches` (buyer) accepts `{ "criteria": Criteria }`:

```json
{"inspirationProjectIds":["project-id"],"description":"A new restaurant website with reservations","serviceCategory":"Website development","budgetCents":500000,"currency":"USD","deliverables":[{"id":"site","label":"Responsive restaurant website","mandatory":true},{"id":"booking","label":"Reservation integration","mandatory":true}],"keywords":["warm","editorial"],"mustHaves":["Reservation integration"],"desiredStandard":"Warm design and mobile accessibility","location":"Kansas City","deliveryMode":"remote","targetDate":"2026-12-01","buyerName":"Optional display name","preferencesConfirmed":true}
```

Fields: `inspirationProjectIds`, `description`, `serviceCategory`, `deliverables`, and `preferencesConfirmed:true` required. `budgetCents` is nullable (unknown), `currency` defaults to USD. `deliverables[].id` is stable and unique; all other fields optional (`keywords`, `mustHaves` default `[]`; text fields default empty; `deliveryMode` defaults `remote`; `targetDate` nullable). Categories match existing catalog. `deliveryMode`: `remote`, `onsite`, or `hybrid`. `preferencesConfirmed:true` records the customer's explicit action to analyze the currently visible, editable requirements.

Success is a full persisted match run `{id,buyerId,criteria,createdAt,status:"complete",version:1,matches:[Match],shortfallReason,mode,trace,evidenceVersion}`. AI owns the Match schema; each match must contain `businessId` and can contain complete business profile, requirement assessments, projects, evidence, gaps, and questions. No invitations are created. `GET /matches/{id}` reloads the owned run. Lambda, or a local API with `ASYNC_ANALYSIS=true`, returns `202 {jobId,status:"pending"}` and performs the analysis after responding; poll the same GET path, which returns `{id,status:"pending"}` until full result is ready (or 503). Jobs and criteria are persisted before scheduling. A failed job or one stalled beyond five minutes surfaces a retryable 503, and retries are explicit. `/health` exposes `asyncAnalysis`.

## Approval and invitation

`POST /deals` (buyer) accepts `{matchRunId,businessIds:["business-id"],approved:true,idempotencyKey:"client-generated-unique-key"}`. Select 1–5 distinct shortlisted businesses. Approval freezes the exact match criteria as `approvedBrief` (and `criteria`). Same key and same payload returns same deal; changed payload returns 409. All child invitations and the parent are one atomic transaction.

Deal response shape: `{id,buyerId,matchRunId,criteria,approvedBrief,briefVersion:1,status:"awaiting_responses"|"responses_received"|"selected",businessIds,requestIds,requests:[Request],proposals:[Proposal],createdAt,approvedAt,selectedRequestId:null|string,selectedBusinessId:null|string,comparison:null|Comparison}`. `GET /deals` returns `{deals:[Deal]}` (buyer only), and `GET /deals/{id}` returns the same full shape. Providers cannot read these routes. Requests preserve existing legacy fields and add `{dealId,criteria,briefVersion,approvedBrief}`; their `brief` remains the legacy `{title,summary,deliverables:string[],questions:[],constraints:string[],reference}`. All recipients get the exact same approved brief. No material edit endpoint; create a new match run and approval to revise.

## Provider response

Existing `GET /requests` serves each provider's own invitation only, and buyers' own requests. Existing `POST /requests/{id}/proposal` retains `{price,currency:"USD",scope,timeline}` and supports optional `{fitStatement,approach,coverage:[{deliverableId,status:"included"|"excluded"|"partial"|"not_stated",detail}],exclusions:string[],assumptions:string[],clarifications:string[],comparableProjectIds:string[],achievementIds:string[]}`. Omitted coverage is `not_stated`, never excluded. Deliverable references must belong to the approved brief; project/achievement references must belong to the responding provider. One immutable proposal per request. Proposals add `priceCents` calculated using Decimal, `version:1`, and `dealId` when applicable.

## Comparison and customer choice

`POST /deals/{id}/compare` (buyer, no body required) generates and persists comparison for the current proposals/evidence. AI owns comparison details. Comparison stores `inputFingerprint` and is omitted/marked stale if inputs change. Live execution may return `202 {jobId,status:"pending"}`; poll `GET /deals/{id}` until `comparison` is present or `comparisonStatus:"failed"`.

`POST /deals/{id}/selection` accepts `{requestId}` (buyer only). Request must be on this deal and have a submitted proposal. Returns updated full Deal. Same selection is idempotent; later explicit selection can replace earlier preference. Selection records preference only, with no payment or contractual acceptance.

Errors use existing `{error:{code,message,fields}}`. Ownership failures return 404; role mismatch 403; schema errors 422; changed idempotency payload/duplicate proposals 409.

## Backend / AI Python boundary

`backend.matching.generate_matches(store, criteria: dict) -> dict` returns `{matches:[{businessId,...}],shortfallReason:str|null,mode:str,trace:list,evidenceVersion:str,...}`. The backend adds ids, owner, criteria and persistence. `backend.matching.compare_deal(store, deal: dict, proposals: list[dict]) -> dict` returns comparison content (`mode`, `trace`, etc.). AI should expose `evidence_fingerprint(store, business_ids:list[str]) -> str` if evidence changes must be included in invalidation; backend will fall back to a canonical catalog/research hash. Functions may raise existing `InferenceUnavailable`; no silent rehearsal on live failure.

## Validated AI outputs

`Match` contains `businessId`, `rank`, `summary`, `comparableProjectIds`, `criteria`, `strengths`, `gaps`, `questions`, `budget`, `evidence`, `achievements`, `emphasisCriteria`.

- `criteria`: `{id,label,status:"supported"|"partial"|"unknown"|"conflict",explanation,evidenceIds:string[]}`. Mandatory criteria also have `mandatory:true`. Confirmed mandatory conflicts are excluded before ranking. Partial style matches are explicitly inferences; current availability is unknown.
- `budget`: `{status:"within_indication"|"unknown"|"conflict",explanation,minimumCents?:number}`. An indication is never a quote. Unknown buyer budget does not exclude candidates.
- `evidence`: `{id,businessId,projectId?,kind:"completed_project"|"website"|"achievement"|"provider_statement",title,url,excerpt,provenance:"sample"|"company_reported"|"community",retrievedAt:string|null,version:number,fixtureCreatedAt?,notice?,cacheStatus?}`. `#project/id`, `#profile/id`, and `#deal/id` refer to in-app records. Fixture website URLs are reserved `.example` domains, with `retrievedAt:null`; they were never fetched. `fixtureCreatedAt` is the sample-data authoring date. Live company pages are company-reported, never independently verified.
- `achievements`: `{title,evidenceIds}` from a completed project owned by the business. Unsupported/mismatched achievement records are omitted.

`Comparison` contains `{mode,generatedAt,evidenceVersion,summary,offers,findings,pendingBusinessIds,trace,notice}`.

- `offers`: `{proposalId,requestId,businessId,priceCents,budgetDifferenceCents:number|null,cheapestDifferenceCents,timeline,fitStatement,approach,demonstratedFit:Match|null,coverage,strengths,gaps,questions,evidence,assumptions,exclusions}`. Positive `budgetDifferenceCents` means over budget. All currency arithmetic uses Decimal to integer cents. Demonstrated fit is distinct from the provider's current offer.
- `coverage`: `{deliverableId,label,status:"included"|"excluded"|"partial"|"not_stated",detail,evidenceIds}`. Omitted coverage stays `not_stated`.
- `findings`: `{id,title,detail,businessIds:string[],evidenceIds:string[],kind:"scope"|"budget"|"fit"|"timeline"|"unknown"}`. Material scope differences cite the relevant provider proposals. Findings do not automatically select a provider.

One Strands orchestrator runs bounded tools. In live mode, the model ranks eligible businesses and selects which grounded criteria to emphasize; for comparison it prioritizes validated evidence-backed findings. Typed tool outputs cannot introduce new business IDs, criterion IDs, evidence IDs, prices or claims. The server renders grounded assertions; model-written prose is not treated as evidence. Rehearsal uses deterministic rankings and remains labeled `mode:"rehearsal"`. Live inference failure raises `InferenceUnavailable` and never falls back to rehearsal.

Live matches and comparisons additionally include `semanticInsights:[{businessIds:string[],detail:string,quotes:[{evidenceId,quote}],evidenceIds:string[],label:"AI inference"}]`. The model submits typed `{detail,evidenceIds}` insights; server code derives business ownership and attaches exact source excerpts. Each supporting quote must be a literal substring of a known source excerpt belonging to one of the stated businesses. A valid quote proves provenance, not the interpretation; the UI must preserve the explicit inference label. Insights cannot change deterministic eligibility, criterion statuses, monetary arithmetic, or customer selection. In rehearsal this list is empty. With `STRANDS_MODEL_MODE=tool`, Bedrock orchestrates retrieval while the final bounded tool calls Akamai to produce the validated analytical output; the direct mode uses Akamai for Strands orchestration and analysis.
