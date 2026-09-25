"""Every setting the application reads, in one place.

Values come from the process environment. A ``.env`` file at the project root is loaded
first if it exists, so a fresh clone needs nothing more than ``cp .env.example .env``
and a key pasted in. Real environment variables always win over the file, which is what
lets CI, Docker and a hosting platform override anything without editing it.

Nothing here makes a network call or imports a provider SDK, so importing the package is
always safe -- including in tests with no credentials at all.
"""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # the dependency is declared; this only guards a partial install
    load_dotenv = None


def _flag(name, default):
    return os.environ.get(name, default).strip().lower() not in ("0", "false", "no", "off", "")


# The repository root: where web/, scenarios/ and .env live. Overridable because an
# installed package cannot find the repository from its own location.
ROOT = Path(os.environ.get("APP_ROOT", Path(__file__).resolve().parents[2]))

if load_dotenv is not None:
    load_dotenv(ROOT / ".env", override=False)


def _path(name, default):
    """A path setting. Relative values are taken from the project root, not the cwd."""
    value = Path(os.environ.get(name) or default)
    return value if value.is_absolute() else ROOT / value

# ── mode ─────────────────────────────────────────────────────────────────────
# Mock mode replays recorded model replies from the scenario's fixtures: deterministic,
# free, and needs no credentials. It is the default everywhere.
MOCK = _flag("MOCK", "1")

# "anthropic" (Claude API, needs ANTHROPIC_API_KEY) or "bedrock" (AWS credentials).
PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic").strip().lower()

# ── Anthropic ────────────────────────────────────────────────────────────────
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-5")

# ── Amazon Bedrock ───────────────────────────────────────────────────────────
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
BEDROCK_MODEL = os.environ.get("BEDROCK_MODEL", "")  # empty: probe MODEL_PREFERENCE

# ── model calls ──────────────────────────────────────────────────────────────
PROMPT_CACHE = _flag("PROMPT_CACHE", "1")
MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "8000"))

# ── the graph ────────────────────────────────────────────────────────────────
MAX_ROUNDS = int(os.environ.get("MAX_ROUNDS", "3"))
MAX_QUESTIONS = int(os.environ.get("MAX_QUESTIONS", "2"))
RECURSION_LIMIT = int(os.environ.get("RECURSION_LIMIT", "40"))

# ── files ────────────────────────────────────────────────────────────────────
# A scenario is one incident plus what the system needs to run it: the runbook risk
# overlay and, for mock mode, one recorded reply file per agent.
SCENARIO_DIR = _path("SCENARIO_DIR", "scenarios/inventory-migration-lock")
INCIDENT_PATH = _path("INCIDENT", SCENARIO_DIR / "incident.json")
OVERLAY_PATH = _path("RUNBOOK_OVERLAY", SCENARIO_DIR / "runbook_overlay.json")
FIXTURES_DIR = _path("FIXTURES", SCENARIO_DIR / "fixtures")
WEB_DIR = _path("WEB_DIR", "web")
MODEL_CACHE_PATH = _path("MODEL_CACHE", ".cache/bedrock-model.txt")


def problems():
    """What is missing for the configured mode to work. Empty means ready.

    Checked at startup and reported by /health, so a live run with no key fails with a
    sentence that says which variable to set, not with a stack trace from the SDK.
    """
    if MOCK:
        return []
    if PROVIDER not in ("anthropic", "bedrock"):
        return [f"LLM_PROVIDER must be 'anthropic' or 'bedrock', not {PROVIDER!r}"]
    if PROVIDER == "anthropic" and not (
        os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    ):
        return ["MOCK=0 with LLM_PROVIDER=anthropic needs ANTHROPIC_API_KEY in .env"]
    return []
