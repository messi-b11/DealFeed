#!/usr/bin/env bash
# Install as root:root 0755 at /usr/local/sbin/dealfeed-release.
# The deploy account may sudo only this entry point. Never run uploaded scripts as root.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
umask 022
cd /
[[ $# == 1 && "$1" =~ ^[0-9a-f]{40}$ ]] || { echo 'One full lowercase Git commit SHA is required.' >&2; exit 2; }
[[ $(id -u) == 0 ]] || { echo 'This activation entry point requires root.' >&2; exit 2; }
commit=$1
exec 9>/run/lock/dealfeed-release.lock
flock -w 600 9
previous=$(readlink -f /opt/dealfeed/current)
[[ "$previous" == /opt/dealfeed/releases/* && -d "$previous" ]] || { echo 'Existing application release is required.' >&2; exit 1; }
[[ -f /etc/dealfeed.env && -f /var/lib/dealfeed/dealfeed.sqlite ]] || { echo 'Existing application configuration and database are required.' >&2; exit 1; }
snapshot=$(mktemp -d /var/lib/dealfeed-release.XXXXXX)
release_dir=$(mktemp -d "/opt/dealfeed/releases/$(date -u +%Y%m%dT%H%M%SZ)-${commit:0:12}.XXXXXX")
chmod 755 "$release_dir"
switched=false
healthy=false
cleanup() {
  result=$?
  trap - EXIT HUP INT TERM
  if [[ "$switched" == true && "$healthy" != true ]]; then
    echo 'Activation failed; restoring previous application release.' >&2
    ln -s "$previous" "$snapshot/rollback"
    mv -Tf "$snapshot/rollback" /opt/dealfeed/current
    systemctl restart dealfeed || true
    result=1
  fi
  rm -rf -- "$snapshot"
  exit "$result"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
# Snapshot uploads through O_NOFOLLOW, then validate the complete archive before extracting.
# BEGIN ARCHIVE_VALIDATION_PYTHON
/usr/bin/python3 -I - "/var/lib/dealfeed-deploy/$commit.tar.gz" "/var/lib/dealfeed-deploy/$commit.sha256" "$snapshot/artifact.tar.gz" "$release_dir" <<'PY'
import hashlib, os, re, shutil, stat, sys, tarfile
from pathlib import Path, PurePosixPath
source, checksum, snapshot, destination = map(Path, sys.argv[1:])
def open_regular(path, maximum):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    handle = os.fdopen(fd, 'rb')
    info = os.fstat(handle.fileno())
    if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
        handle.close()
        raise SystemExit('Upload must be a regular file within the size limit.')
    return handle
with open_regular(checksum, 100) as handle:
    expected = handle.read().decode('ascii').strip()
if not re.fullmatch(r'[0-9a-f]{64}', expected):
    raise SystemExit('Invalid SHA-256 checksum.')
with open_regular(source, 512 * 1024 * 1024) as incoming, snapshot.open('xb') as output:
    shutil.copyfileobj(incoming, output)
with snapshot.open('rb') as handle:
    digest = hashlib.file_digest(handle, 'sha256').hexdigest()
if digest != expected:
    raise SystemExit('Artifact checksum does not match.')
required = {'backend/app.py', 'backend/requirements.lock.txt', 'scripts/serve_app.py', 'out/index.html'}
with tarfile.open(snapshot, 'r:gz') as bundle:
    members = bundle.getmembers()
    names = set()
    expanded_size = 0
    if len(members) > 30000:
        raise SystemExit('Too many artifact members.')
    for member in members:
        name = member.name
        path = PurePosixPath(name)
        allowed = (path.parts and path.parts[0] in {'backend', 'out'}) or name in {'scripts', 'scripts/serve_app.py'}
        if (not allowed or path.is_absolute() or '..' in path.parts or '\\' in name
                or name.startswith('./') or str(path) != name.rstrip('/')
                or not (member.isfile() or member.isdir()) or name in names):
            raise SystemExit('Unsafe or duplicate artifact member: ' + name)
        names.add(name)
        expanded_size += member.size
        if expanded_size > 1024 * 1024 * 1024:
            raise SystemExit('Expanded artifact is too large.')
    if not required.issubset({m.name for m in members if m.isfile()}):
        raise SystemExit('Artifact is missing required application files.')
    lock = bundle.extractfile('backend/requirements.lock.txt').read().decode('utf-8')
    # No pip options, URLs, local paths, editable installs, or source-build hooks.
    if not lock.strip() or any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[A-Za-z0-9_,.-]+\])?==[A-Za-z0-9][A-Za-z0-9_.+!-]*', line) for line in lock.splitlines()):
        raise SystemExit('Dependency lock must contain only exact package==version pins.')
    for member in members:
        target = destination / member.name
        if member.isdir():
            target.mkdir(parents=True, exist_ok=True, mode=0o755)
        else:
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
            with bundle.extractfile(member) as incoming, target.open('xb') as output:
                shutil.copyfileobj(incoming, output)
            target.chmod(0o644)
PY
# END ARCHIVE_VALIDATION_PYTHON
# Keep content-hashed assets available to browsers that still have the preceding HTML.
if [[ -d "$previous/out/_next/static" ]]; then
  install -d -m 755 "$release_dir/out/_next/static"
  cp -an -- "$previous/out/_next/static/." "$release_dir/out/_next/static/"
fi
# Uploaded app code and wheel installation never run with root privileges.
install -d -m 700 -o dealfeed-deploy -g dealfeed-deploy "$release_dir/venv"
runuser -u dealfeed-deploy -- env -i PATH=/usr/bin:/bin HOME=/var/lib/dealfeed-deploy /usr/bin/python3 -I -m venv "$release_dir/venv"
runuser -u dealfeed-deploy -- env -i PATH=/usr/bin:/bin HOME=/var/lib/dealfeed-deploy "$release_dir/venv/bin/python" -I -m pip install --disable-pip-version-check --no-cache-dir --only-binary=:all: --index-url https://pypi.org/simple -q -r "$release_dir/backend/requirements.lock.txt"
chown -hR root:root "$release_dir/venv"
chmod -R a+rX,go-w "$release_dir/venv"
printf '%s\n' "$commit" > "$release_dir/source-commit"
# Back up before starting candidate code: startup may migrate or seed SQLite.
install -d -m 700 -o dealfeed -g dealfeed /var/lib/dealfeed/backups
backup="/var/lib/dealfeed/backups/$(basename "$release_dir").sqlite"
runuser -u dealfeed -- /usr/bin/python3 -I - "$backup" <<'PY'
import os, sqlite3, sys
os.umask(0o077)
with sqlite3.connect('file:/var/lib/dealfeed/dealfeed.sqlite?mode=ro', uri=True) as source:
    with sqlite3.connect(sys.argv[1]) as destination:
        source.backup(destination)
PY
printf '%s\n' "$previous" > /opt/dealfeed/previous-release
ln -s "$release_dir" "$snapshot/current"
switched=true
mv -Tf "$snapshot/current" /opt/dealfeed/current
systemctl restart dealfeed
for attempt in $(seq 1 45); do
  if curl --fail --silent --max-time 5 http://127.0.0.1:8080/api/health > "$snapshot/health.json" && /usr/bin/python3 -I - "$snapshot/health.json" <<'PY'
import json, sys
with open(sys.argv[1]) as handle:
    health = json.load(handle)
assert health.get('status') == 'ok' and health.get('storage') == 'sqlite'
PY
  then
    if curl --fail --silent --max-time 5 http://127.0.0.1:8080/ > "$snapshot/index.html" && cmp -s "$snapshot/index.html" "$release_dir/out/index.html"; then
      healthy=true
      break
    fi
  fi
  sleep 2
done
[[ "$healthy" == true ]] || { echo 'Candidate health check failed.' >&2; exit 1; }
printf 'Deployed commit %s\nRelease: %s\nSQLite backup: %s\n' "$commit" "$release_dir" "$backup"
