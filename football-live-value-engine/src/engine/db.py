from __future__ import annotations
import json, sqlite3
from .config import DB

SCHEMA = """
CREATE TABLE IF NOT EXISTS matches(
  match_key TEXT PRIMARY KEY, date TEXT, league TEXT, home TEXT, away TEXT,
  home_goals REAL, away_goals REAL, status TEXT, source TEXT, source_id TEXT, raw_json TEXT);
CREATE TABLE IF NOT EXISTS odds(
  id INTEGER PRIMARY KEY AUTOINCREMENT, match_key TEXT, observed_at TEXT,
  bookmaker TEXT, market TEXT, selection TEXT, price REAL, source TEXT, raw_json TEXT);
CREATE TABLE IF NOT EXISTS live_snapshots(
  id INTEGER PRIMARY KEY AUTOINCREMENT, match_key TEXT, observed_at TEXT, minute REAL,
  home_score INTEGER, away_score INTEGER, home_stats_json TEXT, away_stats_json TEXT,
  odds_json TEXT, source TEXT);
CREATE TABLE IF NOT EXISTS predictions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, match_key TEXT, phase TEXT,
  market TEXT, selection TEXT, probability REAL, fair_odds REAL, market_odds REAL,
  edge REAL, ev REAL, decision TEXT, model_version TEXT, payload TEXT);
CREATE TABLE IF NOT EXISTS paper_bets(
  id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, match_key TEXT, phase TEXT,
  market TEXT, selection TEXT, odds REAL, probability REAL, stake REAL, status TEXT,
  settled_at TEXT, pnl REAL, payload TEXT);
CREATE TABLE IF NOT EXISTS http_cache(
  cache_key TEXT PRIMARY KEY, fetched_at TEXT, ttl_seconds INTEGER, body TEXT, status INTEGER);
CREATE TABLE IF NOT EXISTS api_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, provider TEXT, path TEXT, status INTEGER, bytes INTEGER);
CREATE INDEX IF NOT EXISTS idx_pred_match ON predictions(match_key, created_at);
CREATE INDEX IF NOT EXISTS idx_paper_status ON paper_bets(status);
"""

def connect() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    return c

def init() -> None:
    c = connect()
    c.executescript(SCHEMA)
    c.commit()
    c.close()

def upsert_match(row: dict) -> None:
    c = connect()
    c.execute(
        """INSERT INTO matches(match_key,date,league,home,away,home_goals,away_goals,status,source,source_id,raw_json)
           VALUES(:match_key,:date,:league,:home,:away,:home_goals,:away_goals,:status,:source,:source_id,:raw_json)
           ON CONFLICT(match_key) DO UPDATE SET
             home_goals=excluded.home_goals, away_goals=excluded.away_goals,
             status=excluded.status, raw_json=excluded.raw_json""",
        {**row, "raw_json": json.dumps(row.get("raw") or {}, default=str)},
    )
    c.commit()
    c.close()

def insert_prediction(row: dict) -> None:
    c = connect()
    c.execute(
        """INSERT INTO predictions(created_at,match_key,phase,market,selection,probability,fair_odds,market_odds,edge,ev,decision,model_version,payload)
           VALUES(datetime('now'),:match_key,:phase,:market,:selection,:probability,:fair_odds,:market_odds,:edge,:ev,:decision,:model_version,:payload)""",
        row,
    )
    c.commit()
    c.close()

def insert_paper(row: dict) -> None:
    c = connect()
    c.execute(
        """INSERT INTO paper_bets(created_at,match_key,phase,market,selection,odds,probability,stake,status,payload)
           VALUES(datetime('now'),:match_key,:phase,:market,:selection,:odds,:probability,:stake,'OPEN',:payload)""",
        row,
    )
    c.commit()
    c.close()
