"""Constants for Dog Assistant."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "dogassistant"
NAME: Final = "Dog Assistant"
PLATFORMS: Final = ["binary_sensor", "calendar", "image", "sensor"]

STORAGE_KEY: Final = f"{DOMAIN}.data"
STORAGE_VERSION: Final = 1
STORAGE_MINOR_VERSION: Final = 4

SUBENTRY_TYPE_DOG: Final = "dog"
FRONTEND_URL: Final = f"/{DOMAIN}/dogassistant-card.js"
FRONTEND_VERSION: Final = "0.3.0"

EVENT_DATA_UPDATED: Final = f"{DOMAIN}_data_updated"

CARE_EVENT_TYPES: Final = {
    "meal",
    "water",
    "treat",
    "walk",
    "toilet",
    "medication",
    "weight",
    "note",
}

RECORD_KINDS: Final = {"medications", "vaccinations", "appointments", "foods", "treats", "commands"}

DEFAULT_SETTINGS: Final = {
    "medication_grace_minutes": 60,
    "appointment_attention_hours": 24,
    "vaccination_attention_days": 30,
    "expiry_attention_days": 30,
}

DOCUMENT_MIME_TYPES: Final = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
MAX_DOCUMENT_BYTES: Final = 10 * 1024 * 1024
MAX_DOCUMENT_STORAGE_BYTES: Final = 50 * 1024 * 1024
MAX_DOCUMENTS: Final = 200
MAX_EVENTS: Final = 50_000
MAX_SHORT_TEXT: Final = 200
MAX_LONG_TEXT: Final = 4_096
