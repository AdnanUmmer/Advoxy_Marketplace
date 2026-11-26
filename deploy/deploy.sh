#!/usr/bin/env bash
# Deploy the latest code on the server: pull, install, migrate, build, collectstatic, restart.
#
#   sudo -u advoxy /srv/advoxy/app/deploy/deploy.sh            # deploy the configured branch
#   sudo -u advoxy BRANCH=release /srv/advoxy/app/deploy/deploy.sh
#
# Runs as the `advoxy` user. Restarting services uses the narrow sudo rule that
# provision.sh installs (systemctl restart advoxy-* only).
set -euo pipefail

APP_DIR="${APP_DIR:-/srv/advoxy/app}"
VENV="${VENV:-/srv/advoxy/venv}"
BRANCH="${BRANCH:-main}"
SOCKET="${SOCKET:-/run/advoxy/gunicorn.sock}"
PY="$VENV/bin/python"

log() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
fail() { printf '\n\033[1;31mDeploy failed: %s\033[0m\n' "$*" >&2; exit 1; }

cd "$APP_DIR"
[ -f .env ] || fail ".env is missing in $APP_DIR (copy deploy/env.production.example and fill it in)"

log "Fetching $BRANCH"
PREVIOUS=$(git rev-parse HEAD)
git fetch --quiet origin "$BRANCH"
git checkout --quiet "$BRANCH"
git reset --quiet --hard "origin/$BRANCH"
CURRENT=$(git rev-parse HEAD)
echo "  $PREVIOUS -> $CURRENT"

log "Installing Python packages"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r requirements.txt

log "Checking production settings"
"$PY" manage.py check --deploy --fail-level ERROR

log "Applying database migrations"
"$PY" manage.py migrate --noinput

log "Building CSS and collecting static files"
"$PY" manage.py build_css
"$PY" manage.py collectstatic --noinput --clear --verbosity 0

log "Creating any missing photo thumbnails"
"$PY" manage.py make_thumbnails

log "Restarting services"
sudo /usr/bin/systemctl restart advoxy-gunicorn advoxy-celery advoxy-celerybeat

log "Health check"
# Ask Gunicorn directly over its socket, as Nginx would after HTTPS (avoids the HTTP->HTTPS redirect).
HOST=$(grep -E '^ALLOWED_HOSTS=' .env | cut -d= -f2 | cut -d, -f1)
for i in 1 2 3 4 5 6 7 8 9 10; do
  if curl --silent --fail --max-time 5 --unix-socket "$SOCKET"        -H "Host: $HOST" -H "X-Forwarded-Proto: https" "http://localhost/healthz/" >/dev/null; then
    log "Deployed $CURRENT"
    exit 0
  fi
  sleep 2
done
echo "Health check failed. Recent Gunicorn log:" >&2
sudo /usr/bin/journalctl -u advoxy-gunicorn -n 40 --no-pager >&2 || true
fail "the site did not answer /healthz/. To roll back: BRANCH=$BRANCH git reset --hard $PREVIOUS and run this script again (migrations are not reversed automatically)."
