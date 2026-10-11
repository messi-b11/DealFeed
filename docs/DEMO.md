# Three-minute DealFeed demo

## Prepare before presenting

Use the private [DealFeed preview](https://dealfeed-work-to-work.jocundbrook.chatgpt.site) after deployment is confirmed in `VERIFICATION.md`. For local development, start the connected stack with `npm run dev:connected`, then open [http://127.0.0.1:3001](http://127.0.0.1:3001). The frontend talks to the API through same-origin `/api`; use one origin and browser throughout so the same buyer identity is recovered.

Confirm the actual mode before the timer starts. The launcher's `AI_MODE` comes from the loaded environment. The starter environment selects rehearsal; a live demonstration requires it to be set to live with the server-side Akamai configuration. Show **Live AI · Akamai + Strands** only when the returned analysis carries that mode. **Rehearsal analysis · No live AI** means deterministic sample analysis, even though the API, persistence, and invitations work.

Rehearse the full journey once. Live analysis is asynchronous with a 120-second inference deadline; a slow call cannot fit comfortably inside a three-minute pitch. Prepare one completed match and a separate comparison deal before presenting. Show a fresh analysis if it finishes within the slot; otherwise identify the prepared result or use a clearly labeled recording. Never describe a prepared result as a new live run.

Prepare the separate comparison deal in this same browser, using the description prefix **Prepared sample comparison** so it is distinguishable from the new deal. Invite three businesses and submit fictional provider-authored responses through their respective provider workspaces. Do not put automatic or fabricated provider submissions into the new deal.

| Prepared response | Quote and timeline | Deliberate scope difference |
| --- | --- | --- |
| Business A | $4,200; six weeks after content is supplied | Includes responsive site and editable menu; explicitly excludes reservation integration in both coverage and scope |
| Business B | $4,800; six weeks after content is supplied | Includes responsive site, editable menu, and reservation integration |
| Business C | $5,800; four weeks after content is supplied | Includes all three deliverables but exceeds the $5,000 target |

These are presentation samples, not actual commercial offers. Keep the fit statements, approach, and exclusions consistent with each response. Link each provider's own comparable completed project and achievement when available. Mark omitted details **Not stated** instead of inventing coverage. Keep the prepared deal open in a second tab, ready to run or show its comparison.

## Timed walkthrough

### 0:00–0:20 — Start with work

“I’m opening a neighborhood restaurant. I can describe a budget, but it’s much easier to show the standard I want.”

Open Poppy & Salt or Olive & Table in the discovery feed. Identify it as completed sample work. Choose **Request something similar**. One project is enough; saving additional inspiration is optional.

### 0:20–0:50 — Make the requirements explicit

Choose **Use restaurant demo requirements**. Show the $5,000 budget target, responsive restaurant website, editable menu, and required reservation integration. Review the desired standard and keywords; edit them if needed. Confirm the visible preferences and select **Find suitable businesses**.

“My requirements control the match. The style suggestion is editable sample metadata, and explicit edits override it.”

If inference is still running, explain that the result is asynchronous and move to the clearly identified prepared analysis. Do not imply the pending run has completed.

### 0:50–1:20 — Inspect five businesses and evidence

Show the five distinct candidates. Their ordering can vary with the confirmed requirements and live analysis. Open **Requirement alignment & questions** on one card, then **Supporting sources**.

“These are evidence-based suggestions. Supported requirements, partial coverage, and unknowns are separate. The .example website findings are labeled fixtures; live AI does not turn sample business claims into verified facts.”

For a live result, show the **AI inference** excerpt and **Analysis tools & sources** trace. Select **Explore business**, inspect the completed portfolio, then return to the shortlist. Point out **Just exploring. No request is sent.**

### 1:20–1:45 — Invite only selected businesses

Select three recipients and choose **Review invitation**. Show their exact names and the frozen shared requirements. Tick the explicit approval and send the request.

“The customer chooses one, several, or all five. Every selected business receives this same brief, exactly once on a retry.”

Show **My deals** with invited, responded, and outstanding counts. Keep this new deal distinct from the prepared comparison deal.

### 1:45–2:15 — Let a provider explain its fit

Open the selected sample **Provider workspace**. Show that its inbox contains only its own invitations. On the prepared request, review the fit statement, approach, comparable work, deliverable coverage, quote, and timeline. If a response was prefilled before the presentation, review and explicitly send it now; otherwise show its already submitted response as prepared sample data.

“The business authors its own approach and commercial terms. Competitors cannot read this private response.”

### 2:15–2:45 — Compare the offer and the evidence

Open the **Prepared sample comparison** deal. Choose **Analyze responses**, or identify the already completed comparison if timing requires it. Use the provider selector to inspect Business A's excluded reservation integration, Business B's full stated coverage, and Business C's above-budget price.

“The lowest quote leaves out a must-have. The comparison cites the response and portfolio evidence. Price differences are calculated in code; unstated terms remain unknown.”

### 2:45–3:00 — Make the customer decision

Inspect Business B, choose it as the preferred provider, and select **Confirm my preferred provider**. Refresh the deal to show the choice persists.

“AI helps me evaluate the fit and tradeoffs. I make the final decision. This records my preference; it does not pay anyone or accept a contract.”

## Copy for one complete sample provider response

Use this only as explicitly fictional provider-authored demo content, adapting coverage and terms to the intended prepared response:

- **Why we fit:** “Our completed restaurant portfolio demonstrates mobile menus, an editorial visual style, and a reservation journey relevant to this brief. This is a prepared sample response.”
- **Proposed approach:** “Confirm the content and reservation service, design mobile layouts, build the approved pages, test keyboard and mobile navigation, and hand over editing access.”
- **Full scope & quote basis:** “A fixed sample quote of $4,800 for a responsive restaurant website, editable menu pages, and integration with the customer's existing reservation service. Includes two design revision rounds and one handover session. Customer supplies copy and photography. Third-party subscription fees are excluded. Taxes are not specified.”
- **Timeline:** “Six weeks after receiving approved content and access to the reservation service.”
- **Assumptions:** “Customer supplies copy and photography.”
- **Clarifications:** “Confirm the reservation platform and account access.”

Mark each requested deliverable **Included** for this full-scope offer and attach relevant evidence from the responding business's own portfolio. Submit with the provider review checkbox. A submitted proposal is immutable in this demo.

## If something fails

Requirements and provider drafts are retained locally; approved deals and submitted proposals are persisted by the API. Retry after a recoverable error, or use **Refresh** to recover the current deal. Do not repeatedly approve with altered recipients while a submission is pending. Changing requirements after approval starts a new match and deal.

If using `npm run dev:local`, say explicitly: “This is the connected rehearsal, with deterministic analysis rather than live AI.” Browser-only rehearsal supports the legacy single-provider flow and does not provide five-business matching.

Live public-site fetching, cloud deployment, and authentication readiness are separate claims from a local live inference demonstration. Use the exact verification record in [VERIFICATION.md](VERIFICATION.md). Do not describe sample websites as fetched, company claims as independently verified, or the demo identity switch as production authentication.
