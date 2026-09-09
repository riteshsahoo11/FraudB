"""
Django settings for BFSI project - MongoDB Only
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Build paths inside the project
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv("SECRET_KEY", "django-insecure-dev-key-change-in-production")

# SECURITY WARNING: don't run with debug turned on in production!
# Default to False for production safety; override in .env
DEBUG = os.getenv("DJANGO_DEBUG", "0") in ("1", "True", "true", "YES")

# ALLOWED_HOSTS = ['localhost', '127.0.0.1', 'testserver'] # for production change to this or required ones 
ALLOWED_HOSTS = ['*']

# Application definition
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
    "accounts",
    # Use AppConfig so we can initialize Mongo indexes at startup
    "api.apps.ApiConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Place Mongo session guard AFTER AuthenticationMiddleware so request.user exists
    "accounts.middleware.MongoSessionMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# MongoDB-only authentication backend
AUTHENTICATION_BACKENDS = [
    'accounts.backends.MongoAuthBackend',
]

ROOT_URLCONF = "project_settings.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [
            BASE_DIR / "core" / "templates",
            BASE_DIR / "accounts" / "templates",
        ],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "project_settings.wsgi.application"

# MongoDB Configuration
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB", "bfsi_db")

# MongoDB Collections
MONGO_COLLECTIONS = {
    'users': 'users',
    'otps': 'otps', 
    'user_activities': 'user_activities',
    # Legacy/compat keys
    'files': 'files',
    'predictions': 'predictions',
    # New collections for the fraud platform
    'fraud_predictions': 'fraud_predictions',
    'file_uploads': 'file_uploads',  # metadata only
    'model_performance': 'model_performance',
    'system_alerts': 'system_alerts',
}

# Minimal SQLite database for Django sessions only
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'sessions.db',
    }
}

# Use minimal Django user model for compatibility
AUTH_USER_MODEL = 'accounts.MinimalUser'

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# Media files
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Email configuration
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "True") == "True"
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER

# Prediction decision threshold (applies to combined risk: ML + rules)
# Set DECISION_THRESHOLD in your .env (e.g., 0.5)
PREDICTION_DECISION_THRESHOLD = float(os.getenv("DECISION_THRESHOLD", "0.5"))

# Enterprise risk policy (can be externalized to Mongo later)
PREDICTION_POLICY = {
    # Global decision
    'decision_threshold': float(os.getenv('DECISION_THRESHOLD', '0.5')),  # combined risk threshold

    # Thresholds
    'amount_high': float(os.getenv('AMOUNT_HIGH', '1000')),               # high amount threshold
    'high_ratio_threshold': float(os.getenv('HIGH_RATIO', '0.1')),        # amount/balance ratio
    'night_hours': (int(os.getenv('NIGHT_START', '22')), int(os.getenv('NIGHT_END', '5'))),
    'velocity_daily_limit': int(os.getenv('VELOCITY_DAILY_LIMIT', '20')),
    'failed_txn_7d_limit': int(os.getenv('FAILED_TXN_7D_LIMIT', '3')),
    'young_account_days_risky': int(os.getenv('YOUNG_ACCOUNT_DAYS_RISKY', '30')),
    'young_account_days_critical': int(os.getenv('YOUNG_ACCOUNT_DAYS_CRIT', '7')),

    # Rule weights (sum capped internally)
    'weights': {
        'HIGH_AMOUNT': float(os.getenv('W_HIGH_AMOUNT', '0.15')),
        'HIGH_AMOUNT_BAL_RATIO': float(os.getenv('W_HIGH_RATIO', '0.20')),
        'NIGHT_TIME': float(os.getenv('W_NIGHT', '0.05')),
        'HIGH_VELOCITY': float(os.getenv('W_VELOCITY', '0.10')),
        'RECENT_FAILURES': float(os.getenv('W_RECENT_FAIL', '0.10')),
        'UNVERIFIED_KYC_RISKY_CHANNEL': float(os.getenv('W_UNVERIFIED_KYC', '0.20')),
        'YOUNG_ACCOUNT_AGE': float(os.getenv('W_YOUNG_ACCOUNT', '0.12')),
    },
    # Max additive adjustment from rules
    'rules_cap': float(os.getenv('RULES_CAP', '0.5')),
}

# Session settings
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_AGE = 86400  # 24 hours

# Login URLs
LOGIN_URL = "/accounts/signin/"
LOGIN_REDIRECT_URL = "/dashboard/"
LOGOUT_REDIRECT_URL = "/"

# File upload settings
FILE_UPLOAD_MAX_MEMORY_SIZE = int(os.getenv("MAX_UPLOAD_SIZE_MB", "50")) * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = FILE_UPLOAD_MAX_MEMORY_SIZE

# OTP settings
OTP_EXPIRY_MINUTES = int(os.getenv("OTP_EXPIRY_MINUTES", "10"))

# Security settings (env-driven)
SECURE_SSL_REDIRECT = os.getenv("SECURE_SSL_REDIRECT", "False") in ("1", "True", "true", "YES")
SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "False") in ("1", "True", "true", "YES")
CSRF_COOKIE_SECURE = os.getenv("CSRF_COOKIE_SECURE", "False") in ("1", "True", "true", "YES")
SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "0"))
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CSRF_TRUSTED_ORIGINS = [o for o in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if o]

# Cookie security settings
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True

# Additional security headers
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# Static files compression
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# Logging configuration
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "level": "INFO",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}

# Create logs directory if it doesn't exist
os.makedirs(BASE_DIR / "logs", exist_ok=True)

# n8n webhooks
N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL", "")
N8N_WEBHOOK_TOKEN = os.getenv("N8N_WEBHOOK_TOKEN", "")

# Required features for batch CSV/JSON validation in Analyze
# You can extend this list without changing code.
REQUIRED_PREDICT_FEATURES = [
    'timestamp',
    'channel',
    'transaction_amount',
]