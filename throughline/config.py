import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    # The hosted FalkorDB lab (falkors:// = TLS). When empty, use the local Docker instance below.
    falkordb_url: str = os.getenv("FALKORDB_URL", "")
    falkordb_host: str = os.getenv("FALKORDB_HOST", "localhost")
    falkordb_port: int = int(os.getenv("FALKORDB_PORT", "6379"))
    graph_name: str = os.getenv("GRAPH_NAME", "throughline")
    clock_start: str = os.getenv("CLOCK_START", "2026-10-28T08:30")
    extract_model: str = os.getenv("OPENAI_EXTRACT_MODEL", "gpt-5.5")
    agent_model: str = os.getenv("OPENAI_AGENT_MODEL", "gpt-5.4-mini")
    conference_id: str = "universe26"
    conference_name: str = "GitHub Universe 2026"
    conference_dates: str = "Oct 28–29, 2026"
    conference_start: str = "2026-10-28"
    conference_end: str = "2026-10-29"
    conference_location: str = "San Francisco, CA"
    raw_snapshot: Path = ROOT / "data" / "raw" / "universe26_feed_2026-10-20.json"
    talks_snapshot: Path = ROOT / "data" / "universe26_talks.jsonl"


settings = Settings()
