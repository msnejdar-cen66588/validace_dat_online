"""Configuration for the AI Validation Pipeline.

Enterprise-ready: supports proxy, custom CA certificates, and feature flags
for running in corporate/restricted network environments.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ═══════════════════════════════════════════════════════════════════════════════
# LLM Providers
# ═══════════════════════════════════════════════════════════════════════════════

# Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")

# OpenAI (standard API – set OPENAI_API_KEY env var on Render)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_API_VERSION = os.getenv("OPENAI_API_VERSION", "")

# ═══════════════════════════════════════════════════════════════════════════════
# External Services
# ═══════════════════════════════════════════════════════════════════════════════

# Mapy.cz
MAPY_CZ_API_KEY = os.getenv("MAPY_CZ_API_KEY", "")

# ČÚZK Katastr nemovitostí REST API
CUZK_API_KEY = os.getenv("CUZK_API_KEY", "")

# Google Cloud Vision
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON", "")
BLOCKED_DOMAINS = ["sreality.cz", "bezrealitky.cz", "idnes.cz"]

# ═══════════════════════════════════════════════════════════════════════════════
# Corporate Network / Proxy / TLS
# ═══════════════════════════════════════════════════════════════════════════════

HTTP_PROXY = os.getenv("HTTP_PROXY", os.getenv("http_proxy", ""))
HTTPS_PROXY = os.getenv("HTTPS_PROXY", os.getenv("https_proxy", ""))
NO_PROXY = os.getenv("NO_PROXY", os.getenv("no_proxy", "localhost,127.0.0.1"))

# Custom CA certificate bundle (for TLS inspection / internal CA)
SSL_CERT_FILE = os.getenv("SSL_CERT_FILE", os.getenv("REQUESTS_CA_BUNDLE", ""))
VERIFY_SSL = os.getenv("VERIFY_SSL", "true").lower() == "true"

# Build proxy dict for httpx
_PROXY_MAP = {}
if HTTPS_PROXY:
    _PROXY_MAP["https://"] = HTTPS_PROXY
if HTTP_PROXY:
    _PROXY_MAP["http://"] = HTTP_PROXY
HTTPX_PROXY = _PROXY_MAP if _PROXY_MAP else None

# SSL verify setting for httpx
HTTPX_VERIFY = SSL_CERT_FILE if SSL_CERT_FILE else VERIFY_SSL

# ═══════════════════════════════════════════════════════════════════════════════
# Feature Flags – disable external services when offline / restricted
# ═══════════════════════════════════════════════════════════════════════════════

ENABLE_MAPS_API = os.getenv("ENABLE_MAPS_API", "true").lower() == "true"
ENABLE_VALUATION = os.getenv("ENABLE_VALUATION", "true").lower() == "true"
ENABLE_EXTERNAL_SERVICES = os.getenv("ENABLE_EXTERNAL_SERVICES", "true").lower() == "true"

# ═══════════════════════════════════════════════════════════════════════════════
# Image Processing
# ═══════════════════════════════════════════════════════════════════════════════

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
MAX_IMAGE_SIZE_BYTES = 300 * 1024  # 300 KB to prevent gateway/proxy payload limits
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tiff", ".bmp"}
SUPPORTED_PDF_EXTENSIONS = {".pdf"}
OUTPUT_FORMAT = "JPEG"
JPEG_QUALITY = 75

# ═══════════════════════════════════════════════════════════════════════════════
# Agent Thresholds — aligned with SEMAFOR methodology
# ═══════════════════════════════════════════════════════════════════════════════

# ── Stáří fotografií (společné pro RD i BJ) ──────────────────────────────────
# Metodika: >180 dní = FAIL, 90–180 dní = WARN, <90 dní = PASS
PHOTO_AGE_FAIL_DAYS = 180   # >180 dní → FAIL (chybí datum = také FAIL)
PHOTO_AGE_WARN_DAYS = 90    # 90–180 dní → WARN

# ── GPS vzdálenost (společné) ─────────────────────────────────────────────────
# Metodika: >1000m = FAIL, 51–1000m = WARN, ≤50m = PASS
GPS_DISTANCE_PASS_M = 50     # do 50 m → PASS
GPS_DISTANCE_WARN_M = 1000   # 51–1000 m → WARN
GPS_DISTANCE_FAIL_M = 1000   # >1000 m → FAIL (chybí GPS = také FAIL)

# ── Detekce manipulace (ForenzníAnalytik) ─────────────────────────────────────
# Metodika: ≥0.9 = FAIL, 0.3–0.89 = WARN
MANIPULATION_SCORE_FAIL = 0.9    # ≥0.9 → FAIL (velmi vysoká pravděpodobnost podvodu)
MANIPULATION_SCORE_WARN = 0.3    # 0.3–0.89 → WARN (eskalace)
# Legacy aliases (used in forenzni_analytik.py)
MANIPULATION_SCORE_THRESHOLD = MANIPULATION_SCORE_FAIL
CONFIDENCE_THRESHOLD = 0.8  # kept for backward compatibility

# ── Kvalita fotografií (společné) ─────────────────────────────────────────────
# Metodika: >30% nekvalitních = FAIL, 10–30% = WARN
PHOTO_QUALITY_FAIL_PERCENT = 30   # >30 % nekvalitních fotek → FAIL
PHOTO_QUALITY_WARN_PERCENT = 10   # 10–30 % → WARN
MIN_PHOTO_WIDTH = 1280            # Minimální šířka fotky (px)
MIN_PHOTO_HEIGHT = 720            # Minimální výška fotky (px)
MIN_BLUR_SCORE = 100.0            # Laplacian variance — pod tímto = rozmazané
MIN_BRIGHTNESS = 40               # Průměrný jas (0–255) — pod tímto = příliš tmavé
MAX_BRIGHTNESS = 245              # Průměrný jas — nad tímto = přesvětlené

# ── GDPR detekce osob/obličejů ────────────────────────────────────────────────
# Metodika: >80% confidence = FAIL, 60–80% = WARN
GDPR_FACE_FAIL_CONFIDENCE = 0.8   # obličej s jistotou >80 % → FAIL
GDPR_FACE_WARN_CONFIDENCE = 0.6   # nejistá detekce 60–80 % → WARN

# ── Strážce RD (rodinný dům) ─────────────────────────────────────────────────
MIN_TOTAL_PHOTOS = 9       # Minimální počet fotek pro RD
MIN_EXTERIOR_PHOTOS = 2    # Minimální počet exteriérových fotek
MIN_INTERIOR_PHOTOS = 3    # Minimální počet interiérových fotek

# ── Strážce BJ (bytová jednotka) ─────────────────────────────────────────────
BJ_MIN_TOTAL_PHOTOS = 4           # Minimální počet fotek pro BJ
BJ_MAX_PHOTO_AGE_DAYS = 30        # Legacy: 1 měsíc (použije se PHOTO_AGE_* pro 3-tier)

# ── Reference ─────────────────────────────────────────────────────────────────
REFERENCE_YEAR = 2026

# ═══════════════════════════════════════════════════════════════════════════════
# Static Frontend (local serving)
# ═══════════════════════════════════════════════════════════════════════════════

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
