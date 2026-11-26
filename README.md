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

The target is an Ubuntu VPS on Hostinger, running Nginx, Gunicorn, PostgreSQL 16 + PostGIS, Redis, and a Celery worker and beat under systemd. `deploy/deploy.sh` and the server configuration ship in milestone 8.
