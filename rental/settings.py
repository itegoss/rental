import os
from pathlib import Path
from dotenv import load_dotenv


# Base directory
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(os.path.join(BASE_DIR, ".env"))
# Load environment variables
load_dotenv(BASE_DIR / ".env")

# Security
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "insecure-secret-key")
DEBUG = os.environ.get("DJANGO_DEBUG", "True") == "True"

ALLOWED_HOSTS = [
    "localhost",
    "127.0.0.1",
    ".app.github.dev",
    "rental-1-yhkm.onrender.com",
    "rental-production-321f.up.railway.app",
    "rental-production-2aa8.up.railway.app",
    "rental-2-sjrr.onrender.com",
    ".onrender.com",
    ".railway.app",
    'rental-5-jl8s.onrender.com', 'localhost', '127.0.0.1'
]

# Installed apps
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "app",
    "social_django",  # social auth
]

# Middleware
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "social_django.middleware.SocialAuthExceptionMiddleware",
]

ROOT_URLCONF = "rental.urls"

# Templates
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.join(BASE_DIR, "app", "templates")],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "social_django.context_processors.backends",
                
            ],
        },
    },
]

WSGI_APPLICATION = "rental.wsgi.application"

# Database
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Static & media
STATIC_URL = "/static/"
STATICFILES_DIRS = [os.path.join(BASE_DIR, "static")]
STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = os.path.join(BASE_DIR, "media")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Authentication backends
AUTHENTICATION_BACKENDS = (
    'social_core.backends.google.GoogleOAuth2',
    'django.contrib.auth.backends.ModelBackend',
)

SOCIAL_AUTH_REDIRECT_IS_HTTPS = True

LOGIN_URL = 'login'
LOGOUT_URL = 'logout'
LOGIN_REDIRECT_URL = '/'   # login ke baad kahaan bhejna hai
LOGOUT_REDIRECT_URL = '/'

# Email config
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "smtp.gmail.com"   # ✅ Gmail use kar rahe ho to ye hona chahiye
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "bhayander@kutchyuvaksangh.org")  # space hatao
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "grre gxin uzwh ftfu")   # ye App Password hona chahiye
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER


# Razorpay API
RAZORPAY_API_KEY = os.environ.get("RAZORPAY_API_KEY")
RAZORPAY_API_SECRET = os.environ.get("RAZORPAY_API_SECRET")

# CSRF & Sessions
CSRF_TRUSTED_ORIGINS = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "https://rental-1-yhkm.onrender.com",
    "https://rental-2-sjrr.onrender.com",
    "https://rental-5-jl8s.onrender.com",
    "https://rental-production-321f.up.railway.app",
    "https://rental-production-2aa8.up.railway.app",
]


    
SESSION_COOKIE_SAMESITE = None
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SAMESITE = None
CSRF_COOKIE_SECURE = False
SESSION_ENGINE = "django.contrib.sessions.backends.db"

# Google OAuth2 keys
SOCIAL_AUTH_GOOGLE_OAUTH2_KEY = os.environ.get("SOCIAL_AUTH_GOOGLE_OAUTH2_KEY")
SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET = os.environ.get("SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET")


DJANGO_DEBUG=True



