#!/usr/bin/env bash
# Install an immutable Ownly release beside existing Apache virtual hosts.
set -Eeuo pipefail
umask 022
revision=${1:?Usage: bash install.sh FULL_COMMIT_SHA}
[[ $EUID -eq 0 && $revision =~ ^[a-f0-9]{40}$ ]] || { echo 'Run as root with a full commit SHA.' >&2; exit 1; }
[[ $(uname -m) == x86_64 ]] || { echo 'This installer targets x86_64.' >&2; exit 1; }
for tool in curl git tar xz sha256sum systemctl apache2ctl certbot; do command -v "$tool" >/dev/null; done
apache2ctl configtest
systemctl is-active --quiet apache2
if [[ ! -e /opt/ownly/current ]]; then
  ! ss -ltn | grep -q ':8850 ' || { echo 'Port 8850 is already in use.' >&2; exit 1; }
fi
install -d -m 0755 /opt/ownly/runtime /opt/ownly/releases /var/www/ownly-acme/.well-known/acme-challenge
node_version=v24.22.0
node_archive="node-${node_version}-linux-x64.tar.xz"
node_sha256=cc2f601cee82d9a5a233302fe307abc600727035fd7d2c3a3571755989e95008
if [[ ! -x /opt/ownly/runtime/node-${node_version}-linux-x64/bin/node ]]; then
  download=$(mktemp -d /tmp/ownly-node.XXXXXX)
  trap 'rm -rf "$download"' EXIT
  curl -fsSL --retry 2 "https://nodejs.org/dist/${node_version}/${node_archive}" -o "$download/$node_archive"
  (cd "$download" && printf '%s  %s\n' "$node_sha256" "$node_archive" | sha256sum --check)
  tar -xJf "$download/$node_archive" -C /opt/ownly/runtime
fi
ln -sfn "/opt/ownly/runtime/node-${node_version}-linux-x64" /opt/ownly/node
if [[ ! -d /opt/ownly/source/.git ]]; then
  git clone --quiet --no-checkout https://github.com/jordi-torras-ai/eada-bootcamp-2026.git /opt/ownly/source
fi
git -C /opt/ownly/source fetch --quiet origin main
git -C /opt/ownly/source cat-file -e "${revision}^{commit}"
release="/opt/ownly/releases/$revision"
if [[ ! -d $release ]]; then
  staged_release=$(mktemp -d /opt/ownly/releases/.new-XXXXXX)
  chmod 0755 "$staged_release"
  git -C /opt/ownly/source archive "$revision" | tar -x -C "$staged_release"
  mv "$staged_release" "$release"
fi
(cd "$release/portal" && /opt/ownly/node/bin/node tests/model.test.mjs && /opt/ownly/node/bin/node --test tests/api.test.mjs tests/http.test.mjs)
previous=$(readlink /opt/ownly/current || true)
[[ ! -e /opt/ownly/current || -L /opt/ownly/current ]] || { echo 'Refusing to replace a non-symlink current path.' >&2; exit 1; }
ln -sfn "$release" /opt/ownly/current
install -m 0644 "$release/deploy/digitalocean/ownly.service" /etc/systemd/system/ownly.service
systemctl daemon-reload
systemctl enable ownly.service
systemctl restart ownly.service
healthy=0
for attempt in {1..15}; do
  if curl -fsS http://127.0.0.1:8850/healthz >/dev/null; then healthy=1; break; fi
  sleep 1
done
if [[ $healthy != 1 ]]; then
  if [[ -n $previous ]]; then ln -sfn "$previous" /opt/ownly/current; systemctl restart ownly.service; fi
  journalctl -u ownly --no-pager -n 20
  exit 1
fi
# This initial HTTP host serves only ACME challenges, never the application.
if [[ ! -e /etc/apache2/sites-available/ownly.torras.ai.conf ]]; then
  install -m 0644 "$release/deploy/digitalocean/ownly-http.conf" /etc/apache2/sites-available/ownly.torras.ai.conf
  a2ensite ownly.torras.ai.conf
  if apache2ctl configtest; then systemctl reload apache2; else a2dissite ownly.torras.ai.conf; exit 1; fi
fi
printf 'ownly-ready\n' > /var/www/ownly-acme/.well-known/acme-challenge/ownly-ready
curl -fsS -H 'Host: ownly.torras.ai' http://127.0.0.1/.well-known/acme-challenge/ownly-ready
printf 'Ownly release %s is healthy on loopback. Add DNS, then run enable-https.sh.\n' "$revision"
