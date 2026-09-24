"""Daily bulletin capture. Designed for 2–4 GitHub Actions runs per day."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from .config import PROCESSED, REPORTS, GOALDIR_KEY
from .db import init, upsert_match, insert_prediction, insert_paper
from .ingest import ingest
from .ratings import build_ratings
from .predict import predict_match
from .providers.espn import scoreboard
from .providers.goaldir import Goaldir
from .backtest import walk_forward
import pandas as pd


def _norm_fx(row: dict, league=None) -> dict:
    odds = row.get("odds") or {}
    if isinstance(odds, list):
        odds = odds[0] if odds and isinstance(odds[0], dict) else {}
    return {
        "id": str(row.get("id") or ""),
        "home": row.get("homeTeamName") or row.get("home"),
        "away": row.get("awayTeamName") or row.get("away"),
        "kickoff": row.get("kickoffUtc") or row.get("kickoff"),
        "league": league or row.get("leagueEspn") or row.get("league") or row.get("leagueName"),
        "status": row.get("matchStatus") or row.get("status") or "scheduled",
        "minute": row.get("matchElapsed"),
        "home_score": row.get("homeTeamScore"),
        "away_score": row.get("awayTeamScore"),
        "odds": odds,
        "source": row.get("source") or "goaldir",
        "raw": row,
    }


def capture() -> dict:
    init()
    hist_path = PROCESSED / "historical_matches.parquet"
    if not hist_path.exists():
        ingest()
    hist = pd.read_parquet(hist_path)
    book = build_ratings(hist)

    sources = ["football-data.co.uk"]
    fixtures = []
    notes = []
    api_calls = 0
    gd = Goaldir()
    if gd.enabled:
        try:
            blob = gd.capture_bulletin()
            fixtures.extend(_norm_fx(x) for x in blob.get("fixtures", []))
            fixtures.extend(_norm_fx(x) for x in blob.get("live", []))
            for r in blob.get("results", []):
                upsert_match({
                    "match_key": f"goaldir:{r.get('id')}",
                    "date": str(r.get("kickoffUtc") or "")[:10],
                    "league": r.get("leagueName"),
                    "home": r.get("homeTeamName"),
                    "away": r.get("awayTeamName"),
                    "home_goals": r.get("homeTeamScore"),
                    "away_goals": r.get("awayTeamScore"),
                    "status": "finished",
                    "source": "goaldir",
                    "source_id": str(r.get("id")),
                    "raw": r,
                })
            try:
                gd.enrich_imminent(blob.get("fixtures") or [])
            except Exception:
                pass
            api_calls = blob.get("api_calls_today") or 0
            sources.append("goaldir")
        except Exception as e:
            notes.append(f"Goaldir: {e}")
    else:
        notes.append("GOALDIR_API_KEY yok — ESPN yedeği.")

    espn = scoreboard()
    sources.append("espn")
    seen = {(f.get("home"), f.get("away"), str(f.get("kickoff"))[:13]) for f in fixtures}
    for e in espn:
        n = _norm_fx(e, league=e.get("leagueEspn"))
        key = (n["home"], n["away"], str(n.get("kickoff"))[:13])
        if key in seen:
            continue
        fixtures.append(n)

    preds = [predict_match(fx, book) for fx in fixtures if fx.get("home") and fx.get("away")]
    picks = [p for p in preds if p.get("pick") and p["pick"]["decision"] in {"STRONG", "CANDIDATE"}]
    for p in preds:
        mk = f"{p.get('kickoff')}|{p.get('home')}|{p.get('away')}"
        pick = p.get("pick") or {}
        insert_prediction({
            "match_key": mk, "phase": p.get("status") or "pre",
            "market": pick.get("market") or "none",
            "selection": pick.get("market") or "none",
            "probability": pick.get("probability"),
            "fair_odds": pick.get("fair_odds"),
            "market_odds": pick.get("market_odds"),
            "edge": pick.get("edge"), "ev": pick.get("ev"),
            "decision": pick.get("decision") or "ABSTAIN",
            "model_version": "kale-dc-elo-v2",
            "payload": json.dumps(p, default=str),
        })
        if pick.get("decision") in {"STRONG", "CANDIDATE"} and pick.get("market_odds"):
            insert_paper({
                "match_key": mk, "phase": "pre", "market": pick["market"],
                "selection": pick["market"], "odds": pick["market_odds"],
                "probability": pick["probability"], "stake": 1.0,
                "payload": json.dumps(p, default=str),
            })

    try:
        bt = walk_forward(hist)
    except Exception as e:
        bt = {"error": str(e)}

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "history_matches": int(len(hist)),
        "fixtures": len(fixtures),
        "predictions": len(preds),
        "picks": picks,
        "all": preds,
        "sources": sources,
        "notes": notes,
        "goaldir": bool(GOALDIR_KEY),
        "api_calls_today": api_calls,
        "backtest": bt,
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "latest.json").write_text(json.dumps(report, indent=2, default=str))
    (REPORTS / "picks.json").write_text(json.dumps(picks, indent=2, default=str))
    return {
        "fixtures": len(fixtures),
        "picks": len(picks),
        "history": int(len(hist)),
        "goaldir": bool(GOALDIR_KEY),
        "api_calls_today": api_calls,
        "notes": notes,
        "report": str(REPORTS / "latest.json"),
    }
