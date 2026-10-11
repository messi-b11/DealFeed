# Deployment

The recommended preview runs the exported Next.js frontend and the connected API on one Ubuntu 24.04 VM. `scripts/serve_app.py` mounts the API at `/api` and serves `out/` at `/`. Build the frontend with `NEXT_PUBLIC_API_URL=/api`. Caddy provides HTTPS and a password gate; uvicorn listens only on `127.0.0.1:8080` with one worker. SQLite data stays outside application releases in `/var/lib/dealfeed`.

The preview uses selectable sample buyer/provider identities. Keep the entire VM application behind the HTTPS gate. An owner-private Sites worker may proxy the VM and attach the gate credentials from its server-side secret environment; neither those credentials nor inference keys belong in browser code. A private Sites frontend alone does not protect an otherwise public API.

## Prerequisites

- A dedicated Ubuntu 24.04 VM, its public IPv4 address, and SSH access as root using the dedicated `.local/dealfeed-deploy` key. The deployment helper configures this VM's Caddy site and `dealfeed` systemd service.
- A DNS hostname resolving to that IP. Allow inbound TCP 80 and 443 for Caddy certificate issuance and HTTPS, and SSH from the operator's address. Port 8080 stays bound to localhost.
- A local Node environment with repository dependencies installed, plus `.venv` containing the backend dependencies. The frontend is built locally, so the VM needs no Node runtime.
- An ignored, permission-restricted environment file containing `AKAMAI_BASE_URL`, `AKAMAI_API_KEY`, and `AKAMAI_MODEL`. Optional `STRANDS_MODEL_MODE` defaults to `direct`. `tool` mode additionally needs the configured Bedrock model and AWS credentials available on the VM. Keep keys out of command arguments, Git, logs, and `NEXT_PUBLIC_*` variables.

Caddy obtains trusted certificates for public DNS names when DNS and ports are configured correctly. A bare IP uses Caddy's local certificate authority by default and is unsuitable for a normal shared browser preview. See [Caddy automatic HTTPS](https://caddyserver.com/docs/automatic-https).

If the user has no domain, an explicitly chosen hostname such as `dealfeed.<IPv4-with-dashes>.sslip.io` can resolve to the VM without changing DNS records. The service documents IP-derived DNS names and ACME certificate issuance; this remains a dependency on an external DNS service, and certificate issuance can be rate-limited. The deploy helper verifies that the selected hostname resolves to the supplied IP before continuing. See [nip.io / sslip.io documentation](https://nip.io/).

## Deploy the private VM preview

After the user provides the IP and the deployment destination is confirmed:

```sh
chmod 600 .local/dealfeed-deploy .local/dealfeed-vm.env
bash scripts/deploy-vm.sh VM_IPV4 PREVIEW_HOSTNAME .local/dealfeed-vm.env
```

Replace `VM_IPV4` and `PREVIEW_HOSTNAME` with the actual values. The helper does the following:

1. Validates the IP/hostname and builds `out/` for `/api`.
2. Packages only the backend, required runtime scripts, and static export. Local databases, SSH keys, and developer environment files are not bundled.
3. Uploads a timestamped release over SSH. Host keys are recorded in `.local/dealfeed-known-hosts`; an existing changed host key is rejected.
4. Installs Python's virtualenv support and Caddy from its official stable package repository, then installs `backend/requirements.lock.txt` into the release virtualenv.
5. Writes a root-readable `/etc/dealfeed.env`, preserving the existing session-signing secret on redeployment. It enables live inference, sample sessions, and asynchronous analysis.
6. Starts the application as the unprivileged `dealfeed` account under systemd. Caddy authenticates every external route, including `/api/sessions` and `/api/health`.
7. Checks HTTPS, rejection without preview credentials, API health, and coexistence of the preview gate with an application session. This checks deployment connectivity; it does not replace a live inference run.

The generated preview username/password are saved only in `.local/dealfeed-preview-PREVIEW_HOSTNAME.json`, with mode `0600`. The helper prints the file path, not its contents. Keep this ignored file for the operator or copy the credentials into the private Sites worker's server-side secret configuration. Passwords are passed to `caddy hash-password` over stdin, and only their hash is written to the Caddyfile. See [Caddy basic authentication](https://caddyserver.com/docs/caddyfile/directives/basic_auth) and [Caddy's Ubuntu installation instructions](https://caddyserver.com/docs/install#debian-ubuntu-raspbian).

Use `DEALFEED_SKIP_BUILD=true` only when the existing `out/` was just built with `NEXT_PUBLIC_API_URL=/api`. The optional fourth argument selects a different SSH key. The helper never changes firewall rules, deletes the database, copies local demo transactions, or exposes uvicorn on a public interface.

## Runtime and authentication details

The systemd service runs this entry point:

```ini
WorkingDirectory=/opt/dealfeed/current
EnvironmentFile=/etc/dealfeed.env
ExecStart=/opt/dealfeed/current/venv/bin/python -m uvicorn scripts.serve_app:app --host 127.0.0.1 --port 8080 --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1
```

`DATABASE_PATH=/var/lib/dealfeed/dealfeed.sqlite` preserves deals, invitations, responses, research, and jobs across release changes. `ASYNC_ANALYSIS=true` returns persisted job IDs promptly and performs matching/comparison in the background. Failed jobs and jobs stalled beyond five minutes become recoverable errors; restarting the service does not automatically replay an interrupted inference call. The browser can reload completed jobs or explicitly retry failed analysis.

Caddy Basic authentication uses the standard `Authorization` header. The browser therefore sends its DealFeed bearer token in `X-DealFeed-Authorization`, with same-origin credentials retained for the preview gate. The API validates that token and still accepts standard bearer `Authorization` from internal scripts. Invalid custom tokens cannot fall back to another identity. Direct cross-origin frontends must allow `X-DealFeed-Authorization` through their CORS layer.

The lockfile's 62 packages declare Python compatibility that includes 3.12 and 3.13, based on installed package metadata. It contains no macOS-specific requirement. The container uses Python 3.13; Ubuntu 24.04 uses Python 3.12. A successful install and smoke test on the target VM remain the final compatibility check. The Dockerfile now installs the same lockfile.

## Operations and rollback

On the VM:

```sh
sudo systemctl status dealfeed caddy --no-pager
sudo journalctl -u dealfeed -n 100 --no-pager
sudo journalctl -u caddy -n 100 --no-pager
curl --fail http://127.0.0.1:8080/api/health
```

Do not print `/etc/dealfeed.env` or the local credentials JSON into logs. Before deleting or replacing the VM, take a SQLite backup and preserve the session-signing secret and Caddy data. For a consistent database backup, run Python's `sqlite3.Connection.backup` API rather than copying a file while writes are active.

Each application release lives in `/opt/dealfeed/releases/`. On redeployment, the prior release path is recorded in `/opt/dealfeed/previous-release`. To roll back application code, point `/opt/dealfeed/current` back to that verified release and restart `dealfeed`. The database remains in `/var/lib/dealfeed`; do not delete it. The deployment helper does not automatically roll back after a failed external HTTPS check because DNS or certificate issuance may still be completing.

## Container alternative

The Dockerfile builds the same `/api` static frontend, installs the locked Python dependencies, and runs as UID 10001. Publish its port only to localhost behind an authenticated HTTPS proxy:

```sh
docker build -t dealfeed .
docker volume create dealfeed-data
docker run -d --name dealfeed --restart unless-stopped \
  --env-file .local/dealfeed-vm.env \
  -e DEMO_AUTH_ENABLED=true -e ASYNC_ANALYSIS=true \
  -v dealfeed-data:/data -p 127.0.0.1:8080:8080 dealfeed
```

For this alternative, add a stable `SESSION_SECRET` to the private environment file and configure the same Caddy gate. The container defaults sample authentication to disabled, so enabling it without a private external gate is not an acceptable public deployment. A bind mount must be writable by UID 10001. A named volume uses the container's prepared `/data` directory.

## AWS alternative

The existing SAM template provides API Gateway, Lambda, DynamoDB, and S3. This is an alternative to the VM, not a dependency of it. Its sample sessions must also be protected before exposing the API. Secrets Manager supplies inference credentials and the session secret. Lambda returns asynchronous match/comparison jobs using self-invocation, and the DynamoDB adapter creates the parent deal and all invitations transactionally.

```sh
sam build --template-file infra/template.yaml --use-container
sam validate --template-file infra/template.yaml --lint
sam deploy --guided --stack-name dealfeed-demo --capabilities CAPABILITY_IAM
```

The build must include `catalog.json` and `service_categories.json`. Configure the exact frontend origin and permit both app authorization headers through API Gateway CORS. A static frontend using a separate API origin must set `NEXT_PUBLIC_API_URL` at build time. Public API Gateway connectivity and configured credentials alone do not establish a successful live model call.

## Post-deploy acceptance

- Without preview authentication, both the homepage and `/api/health` return 401 over HTTPS. Port 8080 is unreachable externally.
- Through the private preview, create a match from one completed project and verify five evidence-supported businesses, explicit source provenance, and the actual returned analysis mode.
- Explore profiles without invitations; approve one through five recipients and retry the same approval without duplicate requests.
- Submit independent provider proposals, verify competitor privacy, compare a material scope difference, and explicitly record a preferred provider.
- Refresh and restart the application; confirm persisted deals, proposals, and preferences remain.
- Verify a real Strands/Akamai analysis and tool trace. Rehearsal behavior must retain its label; failure must never silently turn into a sample result.

The prepared API rehearsal can run inside the VM against `http://127.0.0.1:8080/api`, bypassing only the external preview gate while retaining application ownership checks. Run backend tests, TypeScript checking, and the production frontend build before publishing an updated release.
