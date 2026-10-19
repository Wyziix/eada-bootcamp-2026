#!/usr/bin/env bash
# Use the server's existing ACME account; do not accept new terms automatically.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run as root.' >&2; exit 1; }
[[ -f /opt/ownly/current/deploy/digitalocean/ownly-https.conf ]]
[[ -f /etc/letsencrypt/options-ssl-apache.conf ]]
curl -fsS http://ownly.torras.ai/.well-known/acme-challenge/ownly-ready | grep -qx ownly-ready
certbot certonly --webroot -w /var/www/ownly-acme -d ownly.torras.ai --cert-name ownly.torras.ai --non-interactive --keep-until-expiring --deploy-hook 'systemctl reload apache2'
backup="/etc/apache2/sites-available/ownly.torras.ai.conf.before-https-$(date +%s)"
cp -p /etc/apache2/sites-available/ownly.torras.ai.conf "$backup"
install -m 0644 /opt/ownly/current/deploy/digitalocean/ownly-https.conf /etc/apache2/sites-available/ownly.torras.ai.conf
if apache2ctl configtest; then systemctl reload apache2; else cp -p "$backup" /etc/apache2/sites-available/ownly.torras.ai.conf; exit 1; fi
curl -fsS https://ownly.torras.ai/healthz
printf '\nOwnly HTTPS is ready.\n'
