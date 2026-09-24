from __future__ import annotations
import json
from datetime import datetime, timezone
from .db import connect, init
from .config import GOALDIR_KEY, PROCESSED
from .providers.goaldir import Goaldir
from .providers.espn import scoreboard
from .ratings import build_ratings
from .predict import predict_match
from .config import REPORTS
import pandas as pd


def snapshot(match_key, minute, home_score, away_score, home_stats, away_stats, odds, source):
    init()
    now = datetime.now(timezone.utc).isoformat()
    c = connect()
    c.execute(
        "INSERT INTO live_snapshots(match_key,observed_at,minute,home_score,away_score,home_stats_json,away_stats_json,odds_json,source) VALUES(?,?,?,?,?,?,?,?,?)",
        (match_key, now, minute, home_score, away_score, json.dumps(home_stats), json.dumps(away_stats), json.dumps(odds), source),
    )
    c.commit()
    c.close()


def scan_live() -> dict:
    init()
    hist = pd.read_parquet(PROCESSED / "historical_matches.parquet") if (PROCESSED / "historical_matches.parquet").exists() else None
    book = build_ratings(hist) if hist is not None else {"teams": {}, "leagues": {}}
    live_rows = []
    if GOALDIR_KEY:
        live_rows = Goaldir().fixtures_live()
        source = "goaldir"
    else:
        live_rows = [x for x in scoreboard() if x.get("matchStatus") == "live"]
        source = "espn"
    preds = []
    for row in live_rows:
        fx = {
            "id": row.get("id"),
            "home": row.get("homeTeamName") or row.get("home"),
            "away": row.get("awayTeamName") or row.get("away"),
            "league": row.get("leagueName") or row.get("leagueEspn"),
            "status": "live",
            "minute": row.get("matchElapsed"),
            "home_score": row.get("homeTeamScore"),
            "away_score": row.get("awayTeamScore"),
            "odds": row.get("odds") or {},
            "kickoff": row.get("kickoffUtc"),
        }
        pred = predict_match(fx, book)
        preds.append(pred)
        snapshot(
            f"{fx['home']}|{fx['away']}",
            fx.get("minute") or 0,
            int(float(fx.get("home_score") or 0)),
            int(float(fx.get("away_score") or 0)),
            {}, {}, fx.get("odds") or {}, source,
        )
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "live.json").write_text(json.dumps(preds, indent=2, default=str))
    return {"live": len(preds), "source": source, "path": str(REPORTS / "live.json")}
