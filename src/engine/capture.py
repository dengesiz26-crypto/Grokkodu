"""Daily bulletin capture. Designed for 2–4 GitHub Actions runs per day."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd

from .config import PROCESSED, REPORTS, GOALDIR_KEY
from .db import init, upsert_match, insert_prediction, insert_paper
from .ingest import ingest
from .ratings import build_ratings
from .predict import predict_match
from .providers.espn import scoreboard
from .providers.goaldir import Goaldir
from .backtest import walk_forward


def _norm_fx(row: dict, league=None) -> dict:
    odds = row.get("odds") or {}

    if isinstance(odds, list):
        odds = odds[0] if odds and isinstance(odds[0], dict) else {}

    home_team = row.get("home_team")
    away_team = row.get("away_team")

    if isinstance(home_team, dict):
        home = (
            home_team.get("name")
            or home_team.get("short_name")
            or home_team.get("id")
        )
    else:
        home = (
            row.get("homeTeamName")
            or row.get("home")
            or home_team
        )

    if isinstance(away_team, dict):
        away = (
            away_team.get("name")
            or away_team.get("short_name")
            or away_team.get("id")
        )
    else:
        away = (
            row.get("awayTeamName")
            or row.get("away")
            or away_team
        )

    league_value = league

    if league_value is None:
        league_value = (
            row.get("leagueEspn")
            or row.get("league_id")
            or row.get("leagueName")
            or row.get("league")
        )

    if isinstance(league_value, dict):
        league_value = (
            league_value.get("id")
            or league_value.get("name")
            or league_value.get("short_name")
        )

    kickoff = (
        row.get("kickoffUtc")
        or row.get("kickoff")
        or row.get("event_date")
        or row.get("start_time")
    )

    status = (
        row.get("matchStatus")
        or row.get("status")
        or "scheduled"
    )

    home_score = (
        row.get("home_score")
        if row.get("home_score") is not None
        else row.get("homeTeamScore")
    )

    away_score = (
        row.get("away_score")
        if row.get("away_score") is not None
        else row.get("awayTeamScore")
    )

    return {
        "id": str(row.get("id") or row.get("event_id") or ""),
        "home": home,
        "away": away,
        "kickoff": kickoff,
        "league": league_value,
        "status": status,
        "minute": (
            row.get("current_minute")
            or row.get("matchElapsed")
        ),
        "home_score": home_score,
        "away_score": away_score,
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

            fixtures.extend(
                _norm_fx(x)
                for x in blob.get("fixtures", [])
            )

            fixtures.extend(
                _norm_fx(x)
                for x in blob.get("live", [])
            )

            for r in blob.get("results", []):
                home_team = r.get("home_team")
                away_team = r.get("away_team")

                if isinstance(home_team, dict):
                    home = (
                        home_team.get("name")
                        or home_team.get("short_name")
                        or home_team.get("id")
                    )
                else:
                    home = (
                        r.get("homeTeamName")
                        or r.get("home")
                        or home_team
                    )

                if isinstance(away_team, dict):
                    away = (
                        away_team.get("name")
                        or away_team.get("short_name")
                        or away_team.get("id")
                    )
                else:
                    away = (
                        r.get("awayTeamName")
                        or r.get("away")
                        or away_team
                    )

                league_value = (
                    r.get("league_id")
                    or r.get("leagueName")
                    or r.get("league")
                )

                if isinstance(league_value, dict):
                    league_value = (
                        league_value.get("id")
                        or league_value.get("name")
                        or league_value.get("short_name")
                    )

                home_goals = (
                    r.get("home_score")
                    if r.get("home_score") is not None
                    else r.get("homeTeamScore")
                )

                away_goals = (
                    r.get("away_score")
                    if r.get("away_score") is not None
                    else r.get("awayTeamScore")
                )

                kickoff = (
                    r.get("kickoffUtc")
                    or r.get("kickoff")
                    or r.get("event_date")
                    or r.get("start_time")
                )

                upsert_match({
                    "match_key": f"goaldir:{r.get('id')}",
                    "date": str(kickoff or "")[:10],
                    "league": league_value,
                    "home": home,
                    "away": away,
                    "home_goals": home_goals,
                    "away_goals": away_goals,
                    "status": "finished",
                    "source": "goaldir",
                    "source_id": str(
                        r.get("id") or r.get("event_id") or ""
                    ),
                    "raw": r,
                })

            try:
                gd.enrich_imminent(
                    blob.get("fixtures") or []
                )
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

    seen = {
        (
            f.get("home"),
            f.get("away"),
            str(f.get("kickoff"))[:13],
        )
        for f in fixtures
    }

    for e in espn:
        n = _norm_fx(
            e,
            league=e.get("leagueEspn"),
        )

        key = (
            n["home"],
            n["away"],
            str(n.get("kickoff"))[:13],
        )

        if key in seen:
            continue

        fixtures.append(n)
        seen.add(key)

    # ---------------------------------------------------------
    # MODEL PREDICTIONS
    # ---------------------------------------------------------

    preds = [
        predict_match(fx, book)
        for fx in fixtures
        if fx.get("home") and fx.get("away")
    ]

    # ---------------------------------------------------------
    # PREDICTION LIST
    #
    # STRONG    -> value + prediction candidate
    # CANDIDATE -> value + prediction candidate
    # WATCH     -> prediction candidate
    #
    # ABSTAIN is excluded from the betting prediction list.
    # ---------------------------------------------------------

    picks = [
        p
        for p in preds
        if (
            p.get("pick")
            and p["pick"].get("decision")
            in {"STRONG", "CANDIDATE", "WATCH"}
        )
    ]

    # ---------------------------------------------------------
    # SAVE ALL MODEL PREDICTIONS
    # ---------------------------------------------------------

    for p in preds:
        mk = (
            f"{p.get('kickoff')}|"
            f"{p.get('home')}|"
            f"{p.get('away')}"
        )

        pick = p.get("pick") or {}

        insert_prediction({
            "match_key": mk,
            "phase": p.get("status") or "pre",
            "market": pick.get("market") or "none",
            "selection": pick.get("market") or "none",
            "probability": pick.get("probability"),
            "fair_odds": pick.get("fair_odds"),
            "market_odds": pick.get("market_odds"),
            "edge": pick.get("edge"),
            "ev": pick.get("ev"),
            "decision": pick.get("decision") or "ABSTAIN",
            "model_version": "kale-dc-elo-v2",
            "payload": json.dumps(p, default=str),
        })

        # -----------------------------------------------------
        # PAPER BET
        #
        # Only decisions with an actual market signal are
        # entered into paper_bets.
        #
        # WATCH is now included so the system can measure
        # prediction performance instead of producing zero bets.
        # -----------------------------------------------------

        if (
            pick.get("decision")
            in {"STRONG", "CANDIDATE", "WATCH"}
            and pick.get("market")
            and pick.get("market_odds")
        ):
            insert_paper({
                "match_key": mk,
                "phase": "pre",
                "market": pick["market"],
                "selection": pick["market"],
                "odds": pick["market_odds"],
                "probability": pick["probability"],
                "stake": 1.0,
                "payload": json.dumps(p, default=str),
            })

    # ---------------------------------------------------------
    # BACKTEST
    # ---------------------------------------------------------

    try:
        bt = walk_forward(hist)
    except Exception as e:
        bt = {"error": str(e)}

    # ---------------------------------------------------------
    # REPORT
    # ---------------------------------------------------------

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

    (REPORTS / "latest.json").write_text(
        json.dumps(
            report,
            indent=2,
            default=str,
        )
    )

    (REPORTS / "picks.json").write_text(
        json.dumps(
            picks,
            indent=2,
            default=str,
        )
    )

    return {
        "fixtures": len(fixtures),
        "predictions": len(preds),
        "picks": len(picks),
        "history": int(len(hist)),
        "goaldir": bool(GOALDIR_KEY),
        "api_calls_today": api_calls,
        "notes": notes,
        "report": str(REPORTS / "latest.json"),
    }
