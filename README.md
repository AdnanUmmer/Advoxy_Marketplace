# Advoxy

A pan-African real estate marketplace. Django 5.2, PostgreSQL 16 + PostGIS, Django templates with HTMX and Alpine.js, Tailwind CSS, Celery with Redis, Mapbox GL JS and Stripe.

- Spec: [SPEC.md](SPEC.md)
- Build progress: [PROGRESS.md](PROGRESS.md)
- Open questions and the defaults in use: [QUESTIONS.md](QUESTIONS.md)
- Demo accounts and what to try: [DEMO.md](DEMO.md)

## Local setup

**Windows (this machine):** a portable PostgreSQL 16 + PostGIS lives in `C:\Users\10adn\advoxy-devtools`, and `.env` points GeoDjango at its DLLs (`GDAL_LIBRARY_PATH`, `GEOS_LIBRARY_PATH`, `PROJ_DATA`, `GDAL_DATA`). Start the database, then use the venv:

```powershell
C:\Users\10adn\advoxy-devtools\pgsql\bin\pg_ctl.exe -D C:\Users\10adn\advoxy-devtools\pgdata -l C:\Users\10adn\advoxy-devtools\pg.log -o "-h 127.0.0.1 -p 5432" start
.venv\Scripts\python.exe manage.py runserver
```

**Linux / WSL:** Ubuntu 24.04, natively or in WSL2. To install WSL, run this in an admin PowerShell, then reboot:

```powershell
wsl --install -d Ubuntu-24.04
```

Inside Ubuntu, from the project folder:

```bash
bash scripts/dev_setup_ubuntu.sh        # Postgres 16 + PostGIS, Redis, GDAL, Python 3.12, venv, .env
source ~/.venvs/advoxy/bin/activate
python manage.py migrate
python manage.py build_css              # Tailwind standalone CLI, no Node needed
python manage.py seed_demo              # demo accounts + 77 listings (add --reset to recreate)
python manage.py runserver 0.0.0.0:8000
```

Open http://localhost:8000. Demo logins are in [DEMO.md](DEMO.md).

The setup script writes `.env` from `.env.example` with generated secrets. `.env` is git-ignored. Never commit it.

### Useful commands

| Command | What it does |
|---|---|
| `pytest` | Run the test suite (needs the local Postgres; creates a throwaway test DB) |
| `python manage.py build_css --watch` | Rebuild CSS while you edit templates |
| `python manage.py seed_demo --reset` | Wipe and recreate demo data |
| `celery -A config worker -l info` | Run a worker (only needed when `CELERY_TASK_ALWAYS_EAGER=False`) |

In local dev, `CELERY_TASK_ALWAYS_EAGER=True` runs background tasks inline. Emails print to the console.

### Stripe (test mode)

Put your test keys (`sk_test_…`, `pk_test_…`) in `.env`. Checkout needs no Stripe dashboard setup, and the success page confirms payments directly with Stripe, so local purchases work without webhooks. To also receive webhooks locally (renewals, refunds), install the [Stripe CLI](https://docs.stripe.com/stripe-cli) and run:

```bash
stripe listen --forward-to localhost:8000/billing/webhook/stripe/
```

Then copy the printed `whsec_…` secret into `STRIPE_WEBHOOK_SECRET`. Production webhook setup is in QUESTIONS.md (Q20).

### Sign in with Google (optional)

The Google button appears on the sign-in and sign-up pages once both keys are set:

1. In [Google Cloud console](https://console.cloud.google.com/apis/credentials), create a project, set up the **OAuth consent screen** (External, app name, support email, scopes `openid`, `email`, `profile`).
2. **Create credentials > OAuth client ID > Web application**. Add the authorized redirect URIs `http://localhost:8001/accounts/google/callback/` (local) and `https://YOUR-DOMAIN/accounts/google/callback/` (production).
3. Put the client ID and secret in `.env` as `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`, then restart the server.

People who sign in with Google for the first time pick their roles and accept the terms; their email counts as verified. Google sign-ins link to an existing account with the same email. Staff accounts always use the staff sign-in.

## Configuration

| What | Where |
|---|---|
| Private files (license documents) | `PRIVATE_MEDIA_ROOT` env var (default `private_media/`, never served publicly) |
| Secrets, database URL, Stripe keys, Mapbox token, SMTP | environment variables (`.env`), see `.env.example` |
| Currency | `CURRENCY_CODE`, `CURRENCY_SYMBOL` env vars (default USD / $) |
| Brand name, logo, fonts, contact email | `config/brand.py` |
| Brand colors and font stacks | `static/brand/theme.css` |
| Logo files, home hero image | `static/brand/` (`BRAND["hero_image"]`) |
| Demo banner | `DEMO_MODE=True` (live demo only) |

To rebrand, edit `config/brand.py` and `static/brand/theme.css`, then replace the SVGs in `static/brand/`. Colors are CSS variables, so a color change doesn't need a CSS rebuild.

All user-facing text goes through Django i18n (`{% translate %}` and `gettext`). The site is English only for now.

## Project layout

```
config/            settings, urls, celery, brand.py
apps/core/         public pages, email helper, Celery tasks, seed + build_css commands
apps/accounts/     custom User with role flags, profiles, agencies, agents, auth flows, permissions
apps/listings/     listing models, PostGIS location + geo queries, limits, lifecycle
apps/search/       search filters, map, favorites, saved searches, daily digest
apps/messaging/    inquiries, threads, messages, unread counts, email throttling
apps/agencies/     agent and agency directory, public profiles, team invitations
apps/billing/      payment adapter (Stripe), plans, subscriptions, purchases, featured placements, webhooks
apps/staff/        admin dashboard at /staff/ (overview, moderation, listings, users, verifications)
templates/         Django templates (partials/, accounts/, core/, listings/, emails/)
static/brand/      theme.css + logos (rebrand here)
static/src/app.css Tailwind entry point and design-system components
tests/             pytest suite
seed_assets/       demo listing photos (Unsplash License, see CREDITS.md) used by seed_demo
scripts/           local setup script
deploy/            VPS deployment (milestone 8)
```

## Deployment

Target: an Ubuntu 24.04 VPS (Hostinger KVM or similar, 2 GB RAM or more) running Nginx, Gunicorn, PostgreSQL 16 + PostGIS, Redis, and a Celery worker and beat under systemd, with HTTPS from Let's Encrypt.

| File | What it does |
|---|---|
| `deploy/provision.sh` | One-time server setup: packages, firewall, `advoxy` user, database, virtualenv, `.env`, services, Nginx, HTTPS, nightly backups |
| `deploy/deploy.sh` | Every release: pull, install, `check --deploy`, migrate, build CSS, collectstatic, thumbnails, restart, health check |
| `deploy/env.production.example` | Production settings template (copied to `.env` on the server) |
| `deploy/nginx/advoxy.conf` | Static files cached for a year, media, gzip, upload size, proxy to Gunicorn |
| `deploy/systemd/*.service` | Gunicorn, Celery worker, Celery beat |
| `deploy/backup.sh` | Nightly `pg_dump`, 14 days kept |

**First deploy**

1. Point your domain's A record at the VPS and SSH in as a sudo user.
2. Get the code onto the server and provision it:
   ```bash
   git clone https://github.com/OWNER/Advoxy_Marketplace.git /tmp/advoxy
   sudo DOMAIN=your-domain.com EMAIL=you@your-domain.com REPO=https://github.com/OWNER/Advoxy_Marketplace.git         bash /tmp/advoxy/deploy/provision.sh
   ```
   (For a private repository, add a read-only deploy key for the `advoxy` user first.)
3. Fill in `/srv/advoxy/app/.env`: Stripe keys and webhook secret, Mapbox token, SMTP details, Google keys.
4. Release and create the first admin:
   ```bash
   sudo -u advoxy /srv/advoxy/app/deploy/deploy.sh
   sudo -u advoxy /srv/advoxy/venv/bin/python /srv/advoxy/app/manage.py createsuperuser
   ```
5. In Stripe, add the webhook `https://your-domain.com/billing/webhook/stripe/` (events listed in QUESTIONS.md, Q20). In Google Cloud, add `https://your-domain.com/accounts/google/callback/`.

**Later releases:** push to `main`, then `sudo -u advoxy /srv/advoxy/app/deploy/deploy.sh`.

**Live demo site:** set `DEMO_MODE=True` (shows the demo banner) and run `manage.py seed_demo` once.

**Health check:** `/healthz/` returns `{"ok": true}` when the database and cache answer; point an uptime monitor at it.

**Backups:** dumps are in `/srv/advoxy/backups/`. Restore with `pg_restore --no-owner --dbname=advoxy FILE.dump`. Uploaded photos (`/srv/advoxy/media`) and licence files (`/srv/advoxy/private_media`) are not in the dump; include them in VPS snapshots.
