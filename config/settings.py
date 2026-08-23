"""
Django settings for JCF Organic — inventory & sales for a single-location organic shop.

Configuration is environment driven. See .env.example for every supported variable.
"""

import os
import sys
from pathlib import Path

import dj_database_url
from django.contrib.messages import constants as message_constants
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    raw = os.environ.get(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


# --------------------------------------------------------------------------------------
# Core
# --------------------------------------------------------------------------------------
DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "django-insecure-local-development-key-do-not-use-in-production"  # noqa: S105
    else:
        raise RuntimeError(
            "DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is off. "
            "Generate one with: python manage.py generate_secret_key"
        )

# Development servers may be reached through LAN IPs, device simulators, Docker
# hostnames, or temporary tunnels. Django's host validation is still enforced in
# production, where the allow-list must be supplied explicitly.
ALLOWED_HOSTS = ["*"] if DEBUG else env_list("DJANGO_ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")


def _hostname(value: str) -> str:
    """Platforms are inconsistent about whether they include the scheme."""
    return value.strip().removeprefix("https://").removeprefix("http://").rstrip("/")


def trust_host(host: str, *, public: bool = True) -> None:
    """Allow a host, and trust form posts from it when it is publicly routable."""
    host = _hostname(host)
    if not host:
        return
    if host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(host)
    origin = f"https://{host}"
    if public and origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(origin)


# The host the app answers on is only known at runtime on most platforms, so
# read whichever variable the current one publishes rather than making the
# operator copy it into DJANGO_ALLOWED_HOSTS by hand.
for _var in ("RAILWAY_PUBLIC_DOMAIN", "RENDER_EXTERNAL_HOSTNAME"):
    trust_host(os.environ.get(_var, ""))

# Health probes and container checks arrive over the private network with their
# own Host header, and never over HTTPS, so they are allowed but not trusted as
# CSRF origins.
if os.environ.get("RAILWAY_ENVIRONMENT_NAME") or os.environ.get("RAILWAY_PROJECT_ID"):
    for _internal in (
        os.environ.get("RAILWAY_PRIVATE_DOMAIN", ""),
        "healthcheck.railway.app",
        "localhost",
        "127.0.0.1",
    ):
        trust_host(_internal, public=False)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "django_htmx",
    "apps.core",
    "apps.accounts",
    "apps.catalog",
    "apps.inventory",
    "apps.sales",
    "apps.reports",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    (
        "apps.core.middleware.DevelopmentCsrfViewMiddleware"
        if DEBUG
        else "django.middleware.csrf.CsrfViewMiddleware"
    ),
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "apps.core.middleware.TimezoneAndShopMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.shop_context",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --------------------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------------------
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgres://localhost:5432/jcforganic" if DEBUG else ""
)
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL must be set.")

DATABASES = {
    "default": dj_database_url.parse(
        DATABASE_URL,
        conn_max_age=int(os.environ.get("DB_CONN_MAX_AGE", "60")),
        conn_health_checks=True,
        ssl_require=env_bool("DB_SSL_REQUIRE", False),
    )
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --------------------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"

AUTHENTICATION_BACKENDS = ["apps.accounts.backends.UsernameOrEmailBackend"]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:dashboard"
LOGOUT_REDIRECT_URL = "accounts:login"

# --------------------------------------------------------------------------------------
# Localization — Ghana
# --------------------------------------------------------------------------------------
LANGUAGE_CODE = "en-gb"
TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "Africa/Accra")
USE_I18N = True
USE_TZ = True
USE_THOUSAND_SEPARATOR = True

CURRENCY_SYMBOL = os.environ.get("CURRENCY_SYMBOL", "GH₵")
CURRENCY_CODE = "GHS"

DATE_FORMAT = "j M Y"
DATETIME_FORMAT = "j M Y, H:i"
SHORT_DATE_FORMAT = "d/m/Y"
SHORT_DATETIME_FORMAT = "d/m/Y H:i"
DATE_INPUT_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"]

# --------------------------------------------------------------------------------------
# Static files
# --------------------------------------------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        if not DEBUG
        else "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}
WHITENOISE_MAX_AGE = 31536000

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# --------------------------------------------------------------------------------------
# Sessions & security
# --------------------------------------------------------------------------------------
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_AGE = int(os.environ.get("SESSION_COOKIE_AGE", 60 * 60 * 12))
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = False  # the POS posts via fetch() and reads the token
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
# Railway probes the container over its private HTTP network and requires a
# direct 200 response. Keep every user-facing route HTTPS-only while allowing
# the database-backed readiness check to answer without a redirect.
SECURE_REDIRECT_EXEMPT = [r"^healthz/$"]

DATA_UPLOAD_MAX_NUMBER_FIELDS = 2000

if not DEBUG:
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", 60 * 60 * 24 * 30))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

# --------------------------------------------------------------------------------------
# Messages — map to the theme's alert classes
# --------------------------------------------------------------------------------------
MESSAGE_TAGS = {
    message_constants.DEBUG: "secondary",
    message_constants.INFO: "info",
    message_constants.SUCCESS: "success",
    message_constants.WARNING: "warning",
    message_constants.ERROR: "danger",
}

# --------------------------------------------------------------------------------------
# Logging — never leak stack traces to users; always log them for the operator
# --------------------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "{levelname} {asctime} {name} {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO")},
    "loggers": {
        "django.db.backends": {"level": "WARNING", "handlers": ["console"], "propagate": False},
        "jcf": {"level": "INFO", "handlers": ["console"], "propagate": False},
    },
}

#: Tests run against a real PostgreSQL database, but nobody needs the audit log
#: printed 164 times.
TESTING = "test" in sys.argv or os.environ.get("PYTEST_VERSION") is not None
if TESTING:
    LOGGING["root"]["level"] = "CRITICAL"
    LOGGING["loggers"]["jcf"]["level"] = "CRITICAL"
    # The suite must not depend on whatever is in the developer's .env. With a
    # production-shaped one (DEBUG off, SSL redirect on) every test POST is
    # 301'd to https before it reaches a view, which surfaces as a dozen
    # unrelated failures rather than as the configuration problem it is.
    SECURE_SSL_REDIRECT = False
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False
    SECURE_HSTS_SECONDS = 0
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    STORAGES["staticfiles"] = {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}
    WHITENOISE_AUTOREFRESH = True

# --------------------------------------------------------------------------------------
# Business defaults (overridable per-shop in Settings)
# --------------------------------------------------------------------------------------
DEFAULT_EXPIRY_WARNING_DAYS = 30
DEFAULT_LOW_STOCK_THRESHOLD = 5
PAGE_SIZE = 25
