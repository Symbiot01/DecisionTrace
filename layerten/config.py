import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env", override=True)

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_MAX_CONCURRENCY = max(1, int(os.getenv("GITHUB_MAX_CONCURRENCY", "8")))
GITHUB_HTTP_TIMEOUT_S = float(os.getenv("GITHUB_HTTP_TIMEOUT_S", "60"))
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "")

TARGET_REPO = os.getenv("TARGET_REPO", "567-labs/instructor")
REPO_OWNER, REPO_NAME = TARGET_REPO.split("/", 1)

DATA_DIR = PROJECT_ROOT / "data"
REPO_CLONE_DIR = DATA_DIR / "repo"
RAW_EVENTS_DIR = DATA_DIR / "raw_events"
RAW_EVENTS_PATH = RAW_EVENTS_DIR / "events.jsonl"
CHECKPOINT_PATH = DATA_DIR / "checkpoint.json"

UNIFIED_DIR = DATA_DIR / "unified"
UNIFIED_EVENTS_PATH = UNIFIED_DIR / "events.jsonl"
UNIFIED_TIMELINE_PATH = UNIFIED_DIR / "timeline.jsonl"
UNIFIED_PERSONS_PATH = UNIFIED_DIR / "persons.json"
UNIFIED_BRANCHES_PATH = UNIFIED_DIR / "branches.json"
UNIFIED_LABELS_PATH = UNIFIED_DIR / "labels.json"
UNIFIED_RENAMES_PATH = UNIFIED_DIR / "renames.json"
UNIFIED_FILE_TREE_PATH = UNIFIED_DIR / "file_tree.json"
MERGE_LOG_PATH = UNIFIED_DIR / "merge_log.jsonl"
UNIFIED_INDEX_PATH = UNIFIED_DIR / "index.json"

NEO4J_URI = os.getenv("NEO4J_URI", "")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
GEMINI_MODEL_EXTRACTION = os.getenv("GEMINI_MODEL_EXTRACTION", GEMINI_MODEL)
GEMINI_MODEL_RAG = os.getenv("GEMINI_MODEL_RAG", GEMINI_MODEL)
# Small/cheap model for question parsing. Kept separate so a deprecated model
# cannot silently degrade retrieval to the regex fallback.
GEMINI_MODEL_PARSER = os.getenv("GEMINI_MODEL_PARSER", "gemini-2.5-flash")
GEMINI_MAX_CONCURRENCY = int(os.getenv("GEMINI_MAX_CONCURRENCY", "20"))
GEMINI_RPS = float(os.getenv("GEMINI_RPS", "15"))
GEMINI_REQUEST_TIMEOUT_S = float(os.getenv("GEMINI_REQUEST_TIMEOUT_S", "60"))
# Upper bound on one agentic batch, so a wedged worker cannot stall the run.
AGENTIC_BATCH_TIMEOUT_S = float(os.getenv("AGENTIC_BATCH_TIMEOUT_S", "900"))
GEMINI_MAX_RETRIES = int(os.getenv("GEMINI_MAX_RETRIES", "5"))
PROCESS_CHECKPOINT_PATH = DATA_DIR / "process_checkpoint.json"
NEO4J_BATCH_SIZE = int(os.getenv("NEO4J_BATCH_SIZE", "500"))


def set_target_repo(owner: str, name: str) -> None:
    """Update the active GitHub target for fetch/merge/process (thread-local jobs)."""
    global TARGET_REPO, REPO_OWNER, REPO_NAME
    TARGET_REPO = f"{owner}/{name}"
    REPO_OWNER = owner
    REPO_NAME = name
