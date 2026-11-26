#!/usr/bin/env bash
# One-time setup of a fresh Ubuntu 24.04 VPS (Hostinger KVM or similar) for Advoxy.
#
#   sudo DOMAIN=advoxy.example.com EMAIL=you@example.com REPO=https://github.com/OWNER/Advoxy_Marketplace.git \
#        bash deploy/provision.sh
#
# Installs PostgreSQL 16 + PostGIS, Redis, Nginx, Certbot and Python; creates the `advoxy`
# user, database, virtualenv, systemd services, Nginx site, HTTPS certificate, nightly
# backups and a firewall. Safe to re-run: every step checks before it changes anything.
# It never writes secrets except a generated SECRET_KEY and database password into .env.
set -euo pipefail

: "${DOMAIN:?Set DOMAIN, e.g. DOMAIN=advoxy.example.com}"
: "${EMAIL:?Set EMAIL for HTTPS certificate notices}"
: "${REPO:?Set REPO to the git URL}"
BRANCH="${BRANCH:-main}"
BASE=/srv/advoxy
APP="$BASE/app"
VENV="$BASE/venv"

log() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
[ "$(id -u)" -eq 0 ] || { echo "Run with sudo." >&2; exit 1; }

log "System packages"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  git curl ufw nginx certbot python3-certbot-nginx redis-server \
  postgresql-16 postgresql-16-postgis-3 \
  python3.12 python3.12-venv python3.12-dev build-essential \
  gdal-bin libgdal-dev libgeos-dev libproj-dev libjpeg-dev zlib1g-dev

log "Firewall (SSH, HTTP, HTTPS)"
ufw allow OpenSSH >/dev/null
ufw allow 'Nginx Full' >/dev/null
ufw --force enable >/dev/null

log "App user and folders"
id advoxy >/dev/null 2>&1 || useradd --system --create-home --home-dir "$BASE" --shell /bin/bash advoxy
install -d -o advoxy -g advoxy "$BASE" "$BASE/media" "$BASE/private_media" "$BASE/backups" "$BASE/static"
chmod 751 "$BASE"                      # Nginx (www-data) may pass through to static/ and media/
chmod 755 "$BASE/media"
chmod 750 "$BASE/private_media" "$BASE/backups"   # never readable by Nginx

log "Code"
if [ ! -d "$APP/.git" ]; then
  sudo -u advoxy git clone --branch "$BRANCH" "$REPO" "$APP"
fi

log "Python virtualenv"
[ -d "$VENV" ] || sudo -u advoxy python3.12 -m venv "$VENV"
sudo -u advoxy "$VENV/bin/pip" install --quiet --upgrade pip
sudo -u advoxy "$VENV/bin/pip" install --quiet -r "$APP/requirements.txt"

log "Database"
if [ ! -f "$BASE/.db_password" ]; then
  openssl rand -hex 24 > "$BASE/.db_password"
  chown advoxy:advoxy "$BASE/.db_password"; chmod 600 "$BASE/.db_password"
fi
DB_PASS=$(cat "$BASE/.db_password")
sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='advoxy'" | grep -q 1 \
  || sudo -u postgres psql -qc "CREATE ROLE advoxy LOGIN PASSWORD '$DB_PASS'"
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='advoxy'" | grep -q 1 \
  || sudo -u postgres createdb -O advoxy advoxy
sudo -u postgres psql -q -d advoxy -c "CREATE EXTENSION IF NOT EXISTS postgis"

log "Environment file"
if [ ! -f "$APP/.env" ]; then
  SECRET=$(openssl rand -base64 48 | tr -d '\n/+=')
  sed -e "s|__SECRET_KEY__|$SECRET|" -e "s|__DB_PASSWORD__|$DB_PASS|" -e "s|__DOMAIN__|$DOMAIN|g" \
      "$APP/deploy/env.production.example" > "$APP/.env"
  chown advoxy:advoxy "$APP/.env"; chmod 600 "$APP/.env"
  echo "  Created $APP/.env. Fill in the Stripe, Mapbox, email and Google values, then run deploy.sh."
fi

log "systemd services"
install -m 644 "$APP"/deploy/systemd/advoxy-*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable advoxy-gunicorn advoxy-celery advoxy-celerybeat >/dev/null
# Let the app user restart only its own services (used by deploy.sh).
cat > /etc/sudoers.d/advoxy <<'SUDO'
advoxy ALL=(root) NOPASSWD: /usr/bin/systemctl restart advoxy-gunicorn advoxy-celery advoxy-celerybeat, /usr/bin/journalctl -u advoxy-gunicorn -n 40 --no-pager
SUDO
chmod 440 /etc/sudoers.d/advoxy
visudo -cf /etc/sudoers.d/advoxy >/dev/null

log "Nginx"
sed "s|__DOMAIN__|$DOMAIN|g" "$APP/deploy/nginx/advoxy.conf" > /etc/nginx/sites-available/advoxy
ln -sf /etc/nginx/sites-available/advoxy /etc/nginx/sites-enabled/advoxy
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

log "HTTPS certificate (Let's Encrypt)"
certbot --nginx --non-interactive --agree-tos --redirect -m "$EMAIL" -d "$DOMAIN" || \
  echo "  Certbot failed. Check that $DOMAIN points at this server, then run: certbot --nginx -d $DOMAIN"

log "Nightly database backup (02:30)"
install -m 755 "$APP/deploy/backup.sh" /usr/local/bin/advoxy-backup
echo "30 2 * * * advoxy /usr/local/bin/advoxy-backup >> $BASE/backups/backup.log 2>&1" > /etc/cron.d/advoxy-backup

log "Done"
cat <<NEXT
Next steps:
  1. Edit $APP/.env (Stripe live or test keys, STRIPE_WEBHOOK_SECRET, MAPBOX_TOKEN, SMTP, Google).
  2. sudo -u advoxy $APP/deploy/deploy.sh
  3. sudo -u advoxy $VENV/bin/python $APP/manage.py createsuperuser
     (optional demo data: sudo -u advoxy $VENV/bin/python $APP/manage.py seed_demo, and DEMO_MODE=True)
  4. Stripe dashboard: add the webhook https://$DOMAIN/billing/webhook/stripe/ (events in QUESTIONS.md, Q20).
NEXT
