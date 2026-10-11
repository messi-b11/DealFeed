#!/usr/bin/env bash
# Deploy a private DealFeed preview to a dedicated Ubuntu 24.04 VM.
# Usage: bash scripts/deploy-vm.sh IP HOSTNAME ENV_FILE [SSH_KEY]
# No credentials are printed. Review docs/DEPLOYMENT.md before running.
set -euo pipefail
umask 077
if [[ $# -lt 3 || $# -gt 4 ]]; then
  echo 'Usage: bash scripts/deploy-vm.sh IP HOSTNAME ENV_FILE [SSH_KEY]' >&2
  exit 2
fi
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
vm_ip="$1"
site_hostname="$2"
inference_env="$3"
ssh_key="${4:-$repo_root/.local/dealfeed-deploy}"
python_bin="${DEALFEED_PYTHON:-$repo_root/.venv/bin/python}"
[[ -x "$python_bin" && -f "$inference_env" && -f "$ssh_key" ]] || { echo 'Python virtualenv, environment file, and dedicated SSH key are required.' >&2; exit 2; }
"$python_bin" - "$vm_ip" "$site_hostname" <<'PY'
import ipaddress, re, socket, sys
address, hostname = sys.argv[1:]
if ipaddress.ip_address(address).version != 4 or not ipaddress.ip_address(address).is_global:
    raise SystemExit('Use the VM public IPv4 address.')
if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?', hostname) or '.' not in hostname or '..' in hostname:
    raise SystemExit('Use a DNS hostname without a scheme, port, path, or wildcard.')
try:
    ipaddress.ip_address(hostname)
except ValueError:
    pass
else:
    raise SystemExit('A public DNS hostname is required for a trusted HTTPS certificate.')
resolved = {row[4][0] for row in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)}
if address not in resolved:
    raise SystemExit('The hostname does not resolve to this VM. Fix DNS before deploying.')
PY
cd "$repo_root"
if [[ "${DEALFEED_SKIP_BUILD:-false}" != true ]]; then
  NEXT_PUBLIC_API_URL=/api npm run build
fi
[[ -f out/index.html ]] || { echo 'Missing out/index.html. Build the frontend first.' >&2; exit 2; }
mkdir -p .local
release_id="$(date -u +%Y%m%dT%H%M%SZ)-${RANDOM}"
stage="$(mktemp -d "$repo_root/.local/deploy.XXXXXX")"
trap 'rm -rf "$stage"' EXIT
credential_file="$repo_root/.local/dealfeed-preview-${site_hostname}.json"
"$python_bin" - "$inference_env" "$credential_file" "$stage/settings.json" "$site_hostname" <<'PY'
import json, os, secrets, sys
from pathlib import Path
from dotenv import dotenv_values
source, credential_file, output, hostname = sys.argv[1:]
source_values = dotenv_values(source)
allowed = ['AKAMAI_BASE_URL', 'AKAMAI_API_KEY', 'AKAMAI_MODEL', 'STRANDS_MODEL_MODE', 'BEDROCK_MODEL_ID', 'AWS_REGION', 'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN']
values = {key: source_values[key] for key in allowed if source_values.get(key)}
if any(not values.get(key) for key in ['AKAMAI_BASE_URL', 'AKAMAI_API_KEY', 'AKAMAI_MODEL']):
    raise SystemExit('The environment file needs the three Akamai inference settings.')
if any(any(char in value for char in ['\n', '\r', '\x00']) for value in values.values()):
    raise SystemExit('Environment settings must be single-line values.')
credentials_path = Path(credential_file)
if credentials_path.exists():
    credentials = json.loads(credentials_path.read_text())
else:
    credentials = {'url': 'https://' + hostname, 'username': 'preview', 'password': secrets.token_urlsafe(30)}
    credentials_path.write_text(json.dumps(credentials, indent=2) + '\n')
    os.chmod(credentials_path, 0o600)
Path(output).write_text(json.dumps({'environment': values, 'preview': credentials}))
os.chmod(output, 0o600)
PY
COPYFILE_DISABLE=1 tar --exclude='__pycache__' --exclude='backend/tests' -czf "$stage/release.tgz" backend scripts/serve_app.py scripts/check_inference.py scripts/rehearse_marketplace.py out
cat > "$stage/install.sh" <<'REMOTE'
#!/usr/bin/env bash
set -euo pipefail
umask 077
site_hostname="$1"
release_id="$2"
upload_dir="$3"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip ca-certificates curl gnupg debian-keyring debian-archive-keyring apt-transport-https
if ! command -v caddy >/dev/null 2>&1; then
  curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/gpg.key -o "$upload_dir/caddy.gpg.key"
  gpg --batch --yes --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg "$upload_dir/caddy.gpg.key"
  curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt -o /etc/apt/sources.list.d/caddy-stable.list
  chmod 644 /usr/share/keyrings/caddy-stable-archive-keyring.gpg /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq
  apt-get install -y -qq caddy
fi
id dealfeed >/dev/null 2>&1 || useradd --system --home-dir /var/lib/dealfeed --create-home --shell /usr/sbin/nologin dealfeed
install -d -m 755 /opt/dealfeed/releases
install -d -m 750 -o dealfeed -g dealfeed /var/lib/dealfeed
release_dir="/opt/dealfeed/releases/$release_id"
install -d -m 755 "$release_dir"
tar -xzf "$upload_dir/release.tgz" -C "$release_dir"
chmod -R a+rX "$release_dir"
python3 -m venv "$release_dir/venv"
"$release_dir/venv/bin/pip" install --disable-pip-version-check -q -r "$release_dir/backend/requirements.lock.txt"
chmod -R a+rX "$release_dir"
"$release_dir/venv/bin/python" - "$upload_dir/settings.json" "$site_hostname" <<'PY'
import json, os, secrets, subprocess, sys
from pathlib import Path
from dotenv import dotenv_values
settings_file, hostname = sys.argv[1:]
settings = json.loads(Path(settings_file).read_text())
env_path = Path('/etc/dealfeed.env')
existing = dotenv_values(env_path) if env_path.exists() else {}
values = {**settings['environment'], 'AI_MODE': 'live', 'STRANDS_MODEL_MODE': settings['environment'].get('STRANDS_MODEL_MODE', 'direct'),
          'DEMO_AUTH_ENABLED': 'true', 'ASYNC_ANALYSIS': 'true', 'DATABASE_PATH': '/var/lib/dealfeed/dealfeed.sqlite',
          'SESSION_SECRET': existing.get('SESSION_SECRET') or secrets.token_hex(32), 'ALLOWED_ORIGIN': 'https://' + hostname,
          'PYTHONUNBUFFERED': '1'}
def escaped(value):
    return str(value).replace('\\', '\\\\').replace('"', '\\"')
env_path.write_text(''.join(key + '="' + escaped(value) + '"\n' for key, value in values.items()))
os.chmod(env_path, 0o600)
password_hash = subprocess.run(['caddy', 'hash-password'], input=settings['preview']['password'] + '\n', text=True, capture_output=True, check=True).stdout.strip()
config = f'''{hostname} {{
    basic_auth {{
        preview {password_hash}
    }}
    encode gzip
    header Cache-Control "private, no-store"
    reverse_proxy 127.0.0.1:8080
}}
'''
Path('/etc/caddy/Caddyfile').write_text(config)
os.chmod('/etc/caddy/Caddyfile', 0o640)
PY
chown root:caddy /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
cat > /etc/systemd/system/dealfeed.service <<'UNIT'
[Unit]
Description=DealFeed private marketplace preview
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=dealfeed
Group=dealfeed
WorkingDirectory=/opt/dealfeed/current
EnvironmentFile=/etc/dealfeed.env
ExecStart=/opt/dealfeed/current/venv/bin/python -m uvicorn scripts.serve_app:app --host 127.0.0.1 --port 8080 --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1
Restart=on-failure
RestartSec=3
TimeoutStopSec=310
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/dealfeed
UMask=0077

[Install]
WantedBy=multi-user.target
UNIT
if [[ -L /opt/dealfeed/current ]]; then
  readlink -f /opt/dealfeed/current > /opt/dealfeed/previous-release
fi
ln -sfn "$release_dir" /opt/dealfeed/current
systemctl daemon-reload
systemctl enable dealfeed caddy
systemctl restart dealfeed
for attempt in $(seq 1 30); do
  if curl --fail --silent http://127.0.0.1:8080/api/health > /dev/null; then break; fi
  sleep 1
done
curl --fail --silent http://127.0.0.1:8080/api/health > /dev/null
systemctl reload caddy || systemctl restart caddy
rm -rf "$upload_dir"
REMOTE
ssh_options=(-i "$ssh_key" -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o "UserKnownHostsFile=$repo_root/.local/dealfeed-known-hosts")
remote_stage="/root/dealfeed-upload-$release_id"
ssh "${ssh_options[@]}" "root@$vm_ip" "install -d -m 700 '$remote_stage'"
scp "${ssh_options[@]}" "$stage/release.tgz" "$stage/settings.json" "$stage/install.sh" "root@$vm_ip:$remote_stage/"
ssh "${ssh_options[@]}" "root@$vm_ip" "bash '$remote_stage/install.sh' '$site_hostname' '$release_id' '$remote_stage'"
"$python_bin" - "$credential_file" <<'PY'
import json, sys, time
from pathlib import Path
import httpx
settings = json.loads(Path(sys.argv[1]).read_text())
for attempt in range(60):
    try:
        with httpx.Client(base_url=settings['url'], timeout=10) as client:
            unauthenticated = client.get('/api/health')
            assert unauthenticated.status_code == 401, 'HTTPS preview must require authentication.'
            client.auth = (settings['username'], settings['password'])
            response = client.get('/api/health')
            response.raise_for_status()
            health = response.json()
            assert health['asyncAnalysis'] and health['storage'] == 'sqlite'
            token = client.post('/api/sessions', json={'role': 'buyer'})
            token.raise_for_status()
            account = client.get('/api/deals', headers={'X-DealFeed-Authorization': 'Bearer ' + token.json()['token']})
            account.raise_for_status()
            print('HTTPS gate, persistent API, background jobs, and app identity verified.')
            break
    except (httpx.HTTPError, AssertionError):
        if attempt == 59:
            raise SystemExit('Deployment installed, but HTTPS/auth verification did not finish. Inspect DNS, ports 80/443, and journalctl -u caddy. Credentials remain in the ignored local file.')
        time.sleep(2)
PY
printf 'Private preview: https://%s\nCredentials saved only in: %s\n' "$site_hostname" "$credential_file"
