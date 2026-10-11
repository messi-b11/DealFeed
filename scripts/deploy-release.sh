#!/usr/bin/env bash
# Deploy a CI-built artifact without changing host configuration or secrets.
# Usage: bash scripts/deploy-release.sh HOST ARCHIVE FULL_COMMIT_SHA SSH_KEY KNOWN_HOSTS
set -euo pipefail
umask 077
if [[ $# != 5 ]]; then
  echo 'Usage: deploy-release.sh HOST ARCHIVE FULL_COMMIT_SHA SSH_KEY KNOWN_HOSTS' >&2
  exit 2
fi
host=$1
archive=$2
commit=$3
ssh_key=$4
known_hosts=$5
[[ "$host" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]*$ && "$commit" =~ ^[0-9a-f]{40}$ ]] || { echo 'Invalid host or full Git commit SHA.' >&2; exit 2; }
[[ -f "$archive" && -f "$ssh_key" && -s "$known_hosts" ]] || { echo 'Artifact, SSH key, and pinned known_hosts are required.' >&2; exit 2; }
checksum_file=$(mktemp)
trap 'rm -f "$checksum_file"' EXIT
python3 - "$archive" > "$checksum_file" <<'PY'
import hashlib, sys
with open(sys.argv[1], 'rb') as artifact:
    digest = hashlib.sha256()
    for chunk in iter(lambda: artifact.read(1024 * 1024), b''):
        digest.update(chunk)
print(digest.hexdigest())
PY
ssh_options=(-i "$ssh_key" -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$known_hosts" -o ConnectTimeout=20 -o ServerAliveInterval=15 -o ServerAliveCountMax=4)
remote="dealfeed-deploy@$host"
scp "${ssh_options[@]}" "$archive" "$remote:/var/lib/dealfeed-deploy/$commit.tar.gz"
scp "${ssh_options[@]}" "$checksum_file" "$remote:/var/lib/dealfeed-deploy/$commit.sha256"
ssh "${ssh_options[@]}" "$remote" "sudo -n /usr/local/sbin/dealfeed-release $commit"
