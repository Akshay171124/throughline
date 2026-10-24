import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    falkordb_host: str = os.getenv("FALKORDB_HOST", "localhost")
    falkordb_port: int = int(os.getenv("FALKORDB_PORT", "6379"))
    graph_name: str = os.getenv("GRAPH_NAME", "throughline")
    clock_start: str = os.getenv("CLOCK_START", "2026-10-28T08:30")
    conference_id: str = "universe26"
    conference_name: str = "GitHub Universe 2026"
    raw_snapshot: Path = ROOT / "data" / "raw" / "universe26_feed_2026-10-20.json"
    talks_snapshot: Path = ROOT / "data" / "universe26_talks.jsonl"


settings = Settings()
