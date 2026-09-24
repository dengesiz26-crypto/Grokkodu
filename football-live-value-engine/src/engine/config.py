from __future__ import annotations
import json, os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW, PROCESSED, REPORTS, MODELS, CACHE = (
    DATA / "raw",
    DATA / "processed",
    DATA / "reports",
    DATA / "models",
    DATA / "cache",
)
for p in (RAW, PROCESSED, REPORTS, MODELS, CACHE):
    p.mkdir(parents=True, exist_ok=True)

DB = Path(os.getenv("DATABASE_PATH", str(DATA / "football.db")))
GOALDIR_KEY = (
    os.getenv("GOALDIR_API_KEY") or os.getenv("GOAL_API_KEY") or os.getenv("GOALDIR_KEY") or ""
).strip()
GOALDIR_BASE = os.getenv("GOALDIR_BASE_URL", "https://api.goal-api.com/v1").rstrip("/")
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "").strip()
ODDS_API_IO_KEY = os.getenv("ODDS_API_IO_KEY", os.getenv("ODDS_API_KEY", "")).strip()
EXECUTION_MODE = os.getenv("EXECUTION_MODE", "paper").lower()
ENABLE_LIVE_EXECUTION = os.getenv("ENABLE_LIVE_EXECUTION", "false").lower() == "true"
MIN_EDGE = float(os.getenv("MIN_EDGE", "0.04"))
MIN_PROB = float(os.getenv("MIN_PROB", "0.46"))
MAX_ODDS = float(os.getenv("MAX_ODDS", "3.8"))
MIN_ODDS = float(os.getenv("MIN_ODDS", "1.38"))
LINEUP_HORIZON_HOURS = float(os.getenv("LINEUP_HORIZON_HOURS", "8"))
LINEUP_MAX_PER_RUN = int(os.getenv("LINEUP_MAX_PER_RUN", "18"))


def load_leagues() -> dict:
    return json.loads((ROOT / "config" / "leagues.json").read_text())
