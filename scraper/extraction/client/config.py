"""scraper/extraction/client/config.py — constants."""

MODEL = "gemini-2.5-flash"
DEFAULT_MAX_TOKENS = 4096
MAX_ATTEMPTS_PER_KEY = 3

_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
_KEY_ENV_VARS = ("GOOGLE_AI_KEY", "GOOGLE_AI_KEY_2", "GOOGLE_AI_KEY_3")
