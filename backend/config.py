"""Configuration for the AI Validation Pipeline."""
import os
from dotenv import load_dotenv

load_dotenv()

# Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")

# OpenAI (standard API – set OPENAI_API_KEY env var on Render)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Mapy.cz
MAPY_CZ_API_KEY = os.getenv("MAPY_CZ_API_KEY", "")

# ČÚZK Katastr nemovitostí REST API
CUZK_API_KEY = os.getenv("CUZK_API_KEY", "")

# Google Cloud Vision
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON", "")
BLOCKED_DOMAINS = ["sreality.cz", "bezrealitky.cz", "idnes.cz"]

# Image Processing
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
MAX_IMAGE_SIZE_BYTES = 300 * 1024  # 300 KB to prevent gateway/proxy payload limits
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tiff", ".bmp"}
SUPPORTED_PDF_EXTENSIONS = {".pdf"}
OUTPUT_FORMAT = "JPEG"
JPEG_QUALITY = 75

# Agent Thresholds – Strazce (BR-G4)
MIN_TOTAL_PHOTOS = 9
MIN_EXTERIOR_PHOTOS = 2
MIN_INTERIOR_PHOTOS = 3

# Agent Thresholds – ForenzniAnalytik (BR-G5)
MANIPULATION_SCORE_THRESHOLD = 0.7
CONFIDENCE_THRESHOLD = 0.8

# Agent Thresholds – Strazce BJ (Bytová jednotka)
BJ_MIN_TOTAL_PHOTOS = 4
BJ_MAX_PHOTO_AGE_DAYS = 30   # 1 month (vs 90 days for RD)

# Reference year for age calculations
REFERENCE_YEAR = 2026
