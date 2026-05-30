import os
import json
import logging
from google import genai

logger = logging.getLogger(__name__)

# Dynamically locate Google Cloud service account credentials in backend/
CREDENTIALS_FILE = "/home/aamanprime/Projects/ideathon/backend/annular-form-477012-i9-ba572b97d622.json"
if os.path.exists(CREDENTIALS_FILE):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = CREDENTIALS_FILE
    try:
        with open(CREDENTIALS_FILE, 'r') as f:
            creds_data = json.load(f)
            PROJECT_ID = creds_data.get("project_id", "annular-form-477012-i9")
    except Exception as e:
        logger.error(f"Failed to load credentials file: {e}")
        PROJECT_ID = "annular-form-477012-i9"
else:
    PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "annular-form-477012-i9")

def get_vertex_client() -> genai.Client:
    """Returns a configured, high-performance Vertex AI Client using google-genai SDK."""
    return genai.Client(
        vertexai=True,
        project=PROJECT_ID,
        location="us-central1"
    )
