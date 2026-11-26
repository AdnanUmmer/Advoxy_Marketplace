"""
Django settings for Advoxy.

All secrets and environment-specific values come from environment variables
(see .env.example). Nothing secret is hard-coded here.
"""

from pathlib import Path

import environ
from celery.schedules import crontab
from django.utils.translation import gettext_lazy as _

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    DEMO_MODE=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CSRF_TRUSTED_ORIGINS=(list, []),
    CELERY_TASK_ALWAYS_EAGER=(bool, False),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
DEMO_MODE = env("DEMO_MODE")  # shows the demo banner on the live demo only
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")
SITE_URL = env("SITE_URL", default="http://localhost:8000").rstrip("/")

# ---------------------------------------------------------------------------
# Currency: the single source of truth for money display.
# ---------------------------------------------------------------------------
CURRENCY_CODE = env("CURRENCY_CODE", default="USD")
# Read raw: django-environ would treat a leading "$" as a variable reference.
CURRENCY_SYMBOL = __import__("os").environ.get("CURRENCY_SYMBOL", "$")

# ---------------------------------------------------------------------------
# Apps
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",
    "django.contrib.humanize",
    "django_htmx",
    "apps.core",
    "apps.accounts",
    "apps.listings",
    "apps.search",
    "apps.messaging",
    "apps.staff",
    "apps.billing",
    "apps.agencies",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.accounts.middleware.SuspendedUserMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.site",
            ],
        },
    },
]

# ---------------------------------------------------------------------------
# Database: PostgreSQL 16 + PostGIS
# ---------------------------------------------------------------------------
DATABASES = {"default": env.db("DATABASE_URL", engine="django.contrib.gis.db.backends.postgis")}
DATABASES["default"]["ENGINE"] = "django.contrib.gis.db.backends.postgis"
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Optional overrides for GeoDjango native libraries (only needed on unusual systems).
if env("GDAL_LIBRARY_PATH", default=""):
    GDAL_LIBRARY_PATH = env("GDAL_LIBRARY_PATH")
    import os

    if hasattr(os, "add_dll_directory"):  # Windows: let GDAL find its sibling DLLs
        os.add_dll_directory(str(Path(GDAL_LIBRARY_PATH).parent))
if env("GEOS_LIBRARY_PATH", default=""):
    GEOS_LIBRARY_PATH = env("GEOS_LIBRARY_PATH")

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["apps.accounts.backends.EmailBackend"]
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "accounts:dashboard"
LOGOUT_REDIRECT_URL = "core:home"
STAFF_LOGIN_URL = "accounts:staff_login"
EMAIL_VERIFICATION_MAX_AGE = 60 * 60 * 24 * 3  # 3 days
PASSWORD_RESET_TIMEOUT = 60 * 60 * 24  # 1 day

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------------------
# i18n: English only for now, all strings wrapped for translation.
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en"
LANGUAGES = [("en", _("English"))]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static and media
# ---------------------------------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = env("MEDIA_ROOT", default=str(BASE_DIR / "media"))
# Private files (license documents). Never served directly; staff download them through a checked view.
PRIVATE_MEDIA_ROOT = env("PRIVATE_MEDIA_ROOT", default=str(BASE_DIR / "private_media"))
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

# ---------------------------------------------------------------------------
# Email (SMTP, sent by Celery)
# ---------------------------------------------------------------------------
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Advoxy <no-reply@example.com>")

# ---------------------------------------------------------------------------
# Celery + Redis
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = None
CELERY_TASK_ALWAYS_EAGER = env("CELERY_TASK_ALWAYS_EAGER")
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE = {
    "expire-listings-daily": {"task": "apps.listings.tasks.expire_listings", "schedule": 60 * 60 * 24},
    "end-featured-placements-hourly": {"task": "apps.billing.tasks.end_featured_placements", "schedule": 60 * 60},
    "saved-search-digest-daily": {
        "task": "apps.search.tasks.send_saved_search_digests",
        "schedule": crontab(hour=6, minute=0),  # 06:00 UTC, morning across most of Africa
    },
}

# Listings
LISTING_LIFETIME_DAYS = env.int("LISTING_LIFETIME_DAYS", default=90)
# Markets shown first wherever cities/countries are listed (home, search). Others follow by size.
PRIORITY_COUNTRIES = env.list("PRIORITY_COUNTRIES", default=[
    "Nigeria", "Kenya", "South Africa", "Ghana", "Ethiopia", "Senegal", "DR Congo", "Somalia", "Sudan",
])
LISTING_PHOTO_MAX_MB = 10
LISTING_PHOTO_MAX_EDGE = 2000  # px; larger uploads are downscaled

# ---------------------------------------------------------------------------
# Third-party keys (used in later milestones; always from the environment)
# ---------------------------------------------------------------------------
MAPBOX_TOKEN = env("MAPBOX_TOKEN", default="")
# Sign in with Google: OAuth client from Google Cloud console. The button hides when unset.
GOOGLE_CLIENT_ID = env("GOOGLE_CLIENT_ID", default="")
GOOGLE_CLIENT_SECRET = env("GOOGLE_CLIENT_SECRET", default="")

STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY", default="")
STRIPE_PUBLISHABLE_KEY = env("STRIPE_PUBLISHABLE_KEY", default="")
STRIPE_WEBHOOK_SECRET = env("STRIPE_WEBHOOK_SECRET", default="")
PAYMENT_PROVIDER = "stripe"  # the payment adapter in apps/billing/providers; Stripe is the only one in phase 1

# Prices for one-time purchases (in CURRENCY_CODE). Editable in admin settings in milestone 8.
EXTRA_LISTING_PRICE = env.int("EXTRA_LISTING_PRICE", default=10)
EXTRA_LISTING_DAYS = env.int("EXTRA_LISTING_DAYS", default=30)
FEATURED_PRICE = env.int("FEATURED_PRICE", default=25)
FEATURED_DAYS = env.int("FEATURED_DAYS", default=14)

# ---------------------------------------------------------------------------
# Security (production)
# ---------------------------------------------------------------------------
SESSION_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=60 * 60 * 24 * 30)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
    "loggers": {"stripe": {"level": "WARNING"}},  # the Stripe library logs every request at INFO
}
