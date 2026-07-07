"""Central config — loads environment variables once and exposes them as module-level constants."""
import os

from dotenv import load_dotenv

# Load .env if present (no-op in Docker where env_file already injects vars).
load_dotenv()

# ── Devin v3 API ──────────────────────────────────────────────
DEVIN_API_KEY = os.getenv("DEVIN_API_KEY", "")
DEVIN_ORG_ID = os.getenv("DEVIN_ORG_ID", "")
DEVIN_API_BASE = os.getenv("DEVIN_API_BASE", "https://api.devin.ai").rstrip("/")

# ── GitHub ────────────────────────────────────────────────────
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "ShaunakPandya/superset")
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")

# ── Orchestrator behavior ─────────────────────────────────────
TRIGGER_LABEL = os.getenv("TRIGGER_LABEL", "devin-remediate")
MAX_CONCURRENT_SESSIONS = int(os.getenv("MAX_CONCURRENT_SESSIONS", "3"))
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "45"))
DB_PATH = os.getenv("DB_PATH", "/data/orchestrator.db")

# Categories we recognize from GitHub labels.
KNOWN_CATEGORIES = ("security", "code-quality", "tests", "docs")


def masked(value: str, keep: int = 4) -> str:
    """Return a masked version of a secret for safe logging."""
    if not value:
        return "<unset>"
    if len(value) <= keep:
        return "*" * len(value)
    return value[:keep] + "…" + "*" * 4
