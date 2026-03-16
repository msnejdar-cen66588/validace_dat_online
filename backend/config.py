"""Configuration for the AI Validation Pipeline."""
import os
from dotenv import load_dotenv

load_dotenv()

# Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# OpenAI (GPT-5 via Shared Gateway)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "f6002230db3b4e0581201a2e0f8ae271")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://dev-be.api.csint.cz/be/v1/aigateway-shared-gpt-5")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5") # Or whatever the internal name is, providing a default

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
MAX_IMAGE_SIZE_BYTES = 600 * 1024  # 600 KB to prevent Render OOM on large batches
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

# Reference year for age calculations
REFERENCE_YEAR = 2026
