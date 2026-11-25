#!/usr/bin/env bash
# Local development setup on Ubuntu 24.04 (native or WSL2).
# Installs PostgreSQL 16 + PostGIS, Redis, GeoDjango libraries and Python 3.12,
# creates the database, a virtualenv, and a .env with generated secrets.
# Safe to re-run.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="${VENV_DIR:-$HOME/.venvs/advoxy}"
DB_NAME="${DB_NAME:-advoxy}"
DB_USER="${DB_USER:-advoxy}"

echo "==> Installing system packages"
sudo apt-get update -y
sudo apt-get install -y --no-install-recommends \
  postgresql-16 postgresql-16-postgis-3 postgresql-contrib \
  redis-server \
  gdal-bin libgdal-dev libgeos-dev libproj-dev \
  python3.12 python3.12-venv python3.12-dev build-essential curl

echo "==> Starting services"
sudo service postgresql start
sudo service redis-server start || true

if [ ! -f "$PROJECT_DIR/.env" ]; then
  DB_PASS="$(python3 -c 'import secrets;print(secrets.token_urlsafe(18))')"
  SECRET="$(python3 -c 'import secrets;print(secrets.token_urlsafe(50))')"
  sed -e "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET}|" \
      -e "s|^DATABASE_URL=.*|DATABASE_URL=postgis://${DB_USER}:${DB_PASS}@localhost:5432/${DB_NAME}|" \
      "$PROJECT_DIR/.env.example" > "$PROJECT_DIR/.env"
  echo "==> Wrote .env (not committed)"
else
  DB_PASS="$(grep '^DATABASE_URL=' "$PROJECT_DIR/.env" | sed -E 's|.*://[^:]+:([^@]+)@.*|\1|')"
fi

echo "==> Creating database role and database"
sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${DB_USER}') THEN
    CREATE ROLE ${DB_USER} LOGIN PASSWORD '${DB_PASS}' CREATEDB;
  ELSE
    ALTER ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASS}' CREATEDB;
  END IF;
END \$\$;
SQL
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1 \
  || sudo -u postgres createdb -O "${DB_USER}" "${DB_NAME}"
sudo -u postgres psql -d "${DB_NAME}" -c "CREATE EXTENSION IF NOT EXISTS postgis;"
# The test runner creates a fresh test database and enables PostGIS in it,
# which needs superuser rights. Only for local development.
sudo -u postgres psql -c "ALTER ROLE ${DB_USER} SUPERUSER;"

echo "==> Python virtualenv at $VENV_DIR"
python3.12 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$PROJECT_DIR/requirements-dev.txt"

echo
echo "Done. Next:"
echo "  source $VENV_DIR/bin/activate"
echo "  cd $PROJECT_DIR"
echo "  python manage.py migrate && python manage.py build_css && python manage.py seed_demo"
echo "  python manage.py runserver"
