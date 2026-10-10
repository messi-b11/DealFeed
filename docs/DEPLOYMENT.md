# Deployment

## Current boundary

The frontend can be published as a static rehearsal. AWS deployment and live sponsor inference require credentials that were not available in this workspace. A published rehearsal is not proof of Akamai/Strands connectivity.

## Prerequisites

- AWS CLI and SAM CLI, Docker, a selected AWS profile/region, and permission to deploy the stack.
- Sponsor-provided Akamai base URL/model. Put its API key in an AWS Secrets Manager secret as `{"apiKey":"..."}`. Never place it in `NEXT_PUBLIC_*`, source, shell history, or a committed file.
- Run `python -m scripts.check_inference` with the sponsor credentials first. Use the returned `STRANDS_MODEL_MODE`.
- If fallback is needed, enable a Bedrock model and set its ID/ARN. Cross-region inference profiles need the corresponding underlying model ARNs added to IAM; the template intentionally does not grant wildcard Bedrock access.

## AWS backend

```sh
sam build --template-file infra/template.yaml --use-container
sam validate --template-file infra/template.yaml --lint
sam deploy --guided --stack-name dealfeed-demo --capabilities CAPABILITY_IAM
```

Provide `FrontendOrigin` (exact HTTPS origin, no slash), `AkamaiBaseUrl`, `AkamaiModel`, and `AkamaiSecretArn`. Use `direct` unless the integration test selected `tool`. The template uses Secrets Manager references for Akamai and a generated demo session signing secret. Records and images are retained on stack deletion.

`CodeUri` contains a Makefile that assembles `backend/` and installs dependencies inside the Lambda-compatible container. Lambda runtime: Python 3.13/x86_64, 768 MB, 120 seconds. Brief requests return HTTP 202 and are processed by an asynchronous self-invocation; `/briefs/{id}` returns the result only to the owning sample buyer. Stale jobs become recoverable errors.

Read the `ApiUrl` output. Check `/health` reports `storage=dynamodb`, `mode=live`, and `akamaiConfigured=true`; configuration alone is not an inference test. Then set `NEXT_PUBLIC_API_URL` to that URL **at build time**, rebuild the frontend, and republish.

## Frontend

```sh
NEXT_PUBLIC_API_URL=https://YOUR_API_ID.execute-api.YOUR_REGION.amazonaws.com npm run build
```

The result is in `out/`. The registered private Sites project is configured in `.openai/hosting.json`. Deploy it using the Sites source/package workflow; alternatively host `out/` in an S3/CloudFront frontend distribution. No server-side secrets belong in this static build.

## Post-deploy acceptance

1. Post a completed website project from the sample provider workspace, including a real image upload to S3.
2. Request that project as a buyer. Missing fields must block generation.
3. See real `get_project`, `get_business`, `generate_brief` trace entries and mode `akamai+strands`.
4. Edit and approve the brief. Confirm it appears only in the selected provider’s inbox.
5. Submit a provider price, scope, and timeline; switch to the buyer and refresh.
6. Verify the proposal remains, and wrong buyer/provider sessions cannot access it.
7. Temporarily use an invalid test inference configuration; confirm a recoverable error preserves the buyer’s form and does not create a request.

The demo uses selectable sample identities. Replace the session route with a real identity provider before any real buyer/provider launch. The current kind index is intentionally small-demo oriented; high-volume request listing should use owner-indexed queries and pagination.
