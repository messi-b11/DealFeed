# Verification — October 11, 2026

## Passed

- **91 Python tests** across legacy requests, marketplace ownership, atomic/idempotent Deal creation, provider privacy, immutable proposals, explicit selection, analysis invalidation, async jobs, grounded matching, restricted research, and API/static serving. SQLite is the tested persistent store.
- TypeScript checking and the Next.js 16.4 production static export (`NEXT_PUBLIC_API_URL=/api npm run build`, Webpack).
- Seven private Sites gateway tests covering credential isolation, fixed destination, safe redirects, streamed POST bodies, cancellation, and malformed configuration.
- Full live HTTP acceptance against the production frontend/API server: five distinct matches, exploration without invitations, repeated approval returning the same five child Requests, five independent proposals, cross-account rejection, duplicate proposal rejection, persisted comparison, and explicit saved preference. Matching and comparison both returned `akamai+strands`. The full run took 62.49 seconds; report: `docs/API_LIVE_VERIFICATION.json`.
- Separate optimized inference probe: matching 10.67 and 11.79 seconds, and two-offer comparison 12.50 seconds, with purposeful Strands tool traces and validated literal evidence quotations. These are individual observed runs, not a latency guarantee. Earlier development timeouts are retained in `docs/AI_LIVE_VERIFICATION.json`.
- Real restricted public-web fetching against Python's documentation, recorded in `docs/AI_RESEARCH_VERIFICATION.json`. This verifies fetching and provenance; it does not independently verify any fictional business.
- Ten-intent deterministic matching evaluation: 34 qualified results versus 28 for the keyword baseline, zero hard-conflict or ownership failures, and 9/10 expected top results. This is a fixture evaluation, not a measured live-model accuracy claim. See `docs/MATCH_EVALUATION.json`.

## Connected browser validation

The browser used the real FastAPI/SQLite endpoints for the new marketplace journey. Analysis was explicitly labeled rehearsal for this first interaction sequence:

1. Start from Poppy & Salt, fill the restaurant example, and confirm edited preferences.
2. Receive five distinct businesses with criterion assessments, source provenance, and fixture dates.
3. Explore Studio North without contacting it; select five recipients and approve the displayed frozen brief.
4. Submit Studio North's $4,500 independent offer excluding reservations and Juniper Digital's $4,800 offer including them.
5. Compare both responses; verify the mandatory reservation exclusion, $500/$200 budget differences, and $300 price difference.
6. Explicitly choose Juniper Digital and refresh; the saved preference remains visible.

At 393 × 852, the saved-deal view, requirement composer, and provider response form had document width 393px with no horizontal overflow. All 18 provider form controls fit the viewport, and a saved proposal draft survived reload. Desktop width also matched the viewport. Evidence: `docs/screenshots/marketplace-mobile.jpg`.

A production-serving check discovered a redirect loop between cached Next.js trailing-slash redirects and FastAPI's slash normalization. The combined server now accepts both API slash forms internally; two regression tests pass, and the production browser successfully loaded the connected feed afterward.

The final production browser successfully retried live matching after the AI tool schema was simplified: five businesses appeared with the live Akamai/Strands label and grounded semantic evidence. The earlier failure preserved all requirements and allowed a retry. Evidence: `docs/screenshots/marketplace-live-desktop.jpg`.

A second complete browser journey used live Akamai/Strands analysis: the customer selected two of the five matched businesses, approved the frozen brief, and submitted separate fictional $4,500 Studio North and $4,800 Juniper proposals through their respective workspaces. Live comparison cited the submitted evidence and identified Studio North's missing mandatory reservation integration. The customer explicitly chose Juniper, and the preference persisted after reload. Evidence: `docs/screenshots/marketplace-live-comparison.jpg`.

## Deployment and operational limits

- The Ubuntu VM is deployed at `https://45-79-8-94.sslip.io`. Trusted HTTPS, anonymous-access rejection, authenticated API access, persistent SQLite storage, live-mode configuration, and background jobs passed verification; see `docs/VM_DEPLOYMENT_VERIFICATION.json`.
- The owner-private Sites publication succeeded at 09:21:42 UTC: https://dealfeed-work-to-work.jocundbrook.chatgpt.site. It keeps backend credentials server-side and requires the owner's ChatGPT sign-in. Published source commit: `f2f3274e684c76b14d15f0c90654b6eecb476bad`.
- The deployed VM passed the full five-provider live acceptance journey in 77.50 seconds by 09:21:45 UTC. Matching and comparison both used `akamai+strands`; ownership, atomic retry, independent proposals, comparison persistence, and explicit saved preference passed. See `docs/DEPLOYED_API_VERIFICATION.json`.
- Businesses, projects, achievements, and commercial responses used in verification are fictional sample data. `.example` website fixtures were not fetched.
- Sample buyer/provider identities are intentionally selectable. The preview is private; this is not production business identity verification.
- Inference has a 120-second bound and may fail transiently. Failed jobs preserve input for explicit retry and never silently become rehearsal output. Interrupted jobs are not automatically replayed after a server restart.
- AWS DynamoDB/S3/Lambda deployment and container runtime have not been exercised in an AWS account. The prepared VM uses SQLite and systemd.
