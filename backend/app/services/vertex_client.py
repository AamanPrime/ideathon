import os
import json
import logging
from pathlib import Path
from typing import Optional

from google import genai

from app.config import get_settings

logger = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parents[2]


def _locate_credentials() -> Optional[str]:
    """Find the gitignored GCP service-account JSON (never committed)."""
    s = get_settings()
    candidates: list[Path] = []
    cfg = (s.google_application_credentials or "").strip()
    if cfg:
        p = Path(cfg)
        candidates.append(p if p.is_absolute() else _BACKEND_DIR / p)
    candidates.append(_BACKEND_DIR / "gcp_service_account.json")
    candidates.append(_BACKEND_DIR / "annular-form-477012-i9-ba572b97d622.json")
    candidates.extend(sorted(_BACKEND_DIR.glob("*service_account*.json")))
    for c in candidates:
        if c and c.exists():
            return str(c)
    return None


CREDENTIALS_FILE = _locate_credentials()
PROJECT_ID = get_settings().gemini_project_id or "annular-form-477012-i9"
if CREDENTIALS_FILE:
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = CREDENTIALS_FILE
    try:
        with open(CREDENTIALS_FILE, "r") as f:
            creds_data = json.load(f)
            PROJECT_ID = creds_data.get("project_id", PROJECT_ID)
    except Exception as e:
        logger.error(f"Failed to load credentials file: {e}")
else:
    PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", PROJECT_ID)


def get_vertex_client() -> genai.Client:
    """Returns a configured, high-performance Vertex AI Client using google-genai SDK."""
    return genai.Client(
        vertexai=True,
        project=PROJECT_ID,
        location=get_settings().vertex_location or "us-central1",
    )
