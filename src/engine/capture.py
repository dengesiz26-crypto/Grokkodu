"""Daily bulletin capture.

Goaldir supplies football data.
The Odds API supplies real bookmaker market odds.
KALE produces its own probabilities and predictions.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd
import requests

from .config import (
    PROCESSED,
    REPORTS,
    GOALDIR_KEY,
)
from .db import (
    init,
    upsert_match,
    insert_prediction,
    insert_paper,
)
from .ingest import ingest
from .ratings import build_ratings
from .predict import predict_match
from .providers.espn import scoreboard
from .providers.goaldir import Goaldir
from .backtest import walk_forward


# ============================================================
# THE ODDS API
# ============================================================

ODDS_API_BASE = "https://api.the-odds-api.com/v4"
ODDS_API_KEY = __import__("os").getenv("ODDS_API_IO_KEY", "").strip()

# One region is deliberately used to keep API usage controlled.
ODDS_API_REGIONS = "us"

# The Odds API v4 documented featured markets.
ODDS_API_MARKETS = "h2h,totals"

# Common football league -> The Odds API sport key mapping.
# Unknown leagues are not guessed.
ODDS_SPORT_KEYS = {
    "premier league": "soccer_epl",
    "england premier league": "soccer_epl",
    "epl": "soccer_epl",

    "championship": "soccer_efl_champ",
    "english championship": "soccer_efl_champ",

    "la liga": "soccer_spain_la_liga",
    "laliga": "soccer_spain_la_liga",
    "primera division": "soccer_spain_la_liga",

    "serie a": "soccer_italy_serie_a",

    "bundesliga": "soccer_germany_bundesliga",

    "ligue 1": "soccer_france_ligue_one",

    "eredivisie": "soccer_netherlands_eredivisie",

    "primeira liga": "soccer_portugal_primeira_liga",
    "portuguese primeira liga": "soccer_portugal_primeira_liga",

    "super lig": "soccer_turkey_super_league",
    "super league": "soccer_turkey_super_league",

    "mls": "soccer_usa_mls",

    "brasileirao": "soccer_brazil_campeonato",
    "brazil serie a": "soccer_brazil_campeonato",

    "liga mx": "soccer_mexico_ligamx",

    "argentina primera division": "soccer_argentina_primera_division",

    "scottish premiership": "soccer_spl",

    "uefa champions league": "soccer_uefa_champs_league",
    "champions league": "soccer_uefa_champs_league",

    "uefa europa league": "soccer_uefa_europa_league",
    "europa league": "soccer_uefa_europa_league",

    "uefa conference league": "soccer_uefa_europa_conference_league",
}


def _norm_name(value) -> str:
    if value is None:
        return ""

    return (
        str(value)
        .strip()
        .lower()
        .replace(".", "")
        .replace("'", "")
        .replace("-", " ")
    )


def _team_name(value):
    if isinstance(value, dict):
        return (
            value.get("name")
            or value.get("short_name")
            or value.get("display_name")
            or value.get("id")
        )

    return value


def _league_name(row: dict) -> str:
    value = (
        row.get("leagueName")
        or row.get("league")
        or row.get("league_name")
    )

    if isinstance(value, dict):
        value = (
            value.get("name")
            or value.get("title")
            or value.get("short_name")
        )

    return str(value or "").strip()


def _sport_key_for_fixture(fx: dict):
    league = _league_name(fx)
    normalized = _norm_name(league)

    if normalized in ODDS_SPORT_KEYS:
        return ODDS_SPORT_KEYS[normalized]

    # Try direct sport key if Goaldir already supplies one.
    raw = (
        fx.get("sport_key")
        or fx.get("odds_sport_key")
        or fx.get("sport")
    )

    if raw:
        raw = str(raw).strip()

        if raw.startswith("soccer_"):
            return raw

    return None


def _odds_api_get(
    sport_key: str,
    *,
    event_ids: str | None = None,
):
    if not ODDS_API_KEY:
        return []

    params = {
        "apiKey": ODDS_API_KEY,
        "regions": ODDS_API_REGIONS,
        "markets": ODDS_API_MARKETS,
        "oddsFormat": "decimal",
        "dateFormat": "iso",
    }

    if event_ids:
        params["eventIds"] = event_ids

    response = requests.get(
        f"{ODDS_API_BASE}/sports/{sport_key}/odds/",
        params=params,
        timeout=30,
    )

    response.raise_for_status()

    data = response.json()

    if not isinstance(data, list):
        return []

    return data


def _choose_best_h2h(
    event: dict,
    home: str,
    away: str,
):
    prices = {
        "home": [],
        "draw": [],
        "away": [],
    }

    home_n = _norm_name(home)
    away_n = _norm_name(away)

    for bookmaker in event.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            if market.get("key") != "h2h":
                continue

            for outcome in market.get("outcomes", []):
                name = _norm_name(outcome.get("name"))
                price = outcome.get("price")

                try:
                    price = float(price)
                except (TypeError, ValueError):
                    continue

                if price <= 1:
                    continue

                if name == home_n:
                    prices["home"].append(price)

                elif name == away_n:
                    prices["away"].append(price)

                elif name == "draw":
                    prices["draw"].append(price)

    result = {}

    for key, values in prices.items():
        if values:
            # Best available real bookmaker price.
            result[key] = max(values)

    return result


def _choose_totals(event: dict):
    over = []
    under = []

    for bookmaker in event.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            if market.get("key") != "totals":
                continue

            for outcome in market.get("outcomes", []):
                name = str(outcome.get("name") or "").lower()
                point = outcome.get("point")
                price = outcome.get("price")

                try:
                    point = float(point)
                    price = float(price)
                except (TypeError, ValueError):
                    continue

                if point != 2.5 or price <= 1:
                    continue

                if name == "over":
                    over.append(price)

                elif name == "under":
                    under.append(price)

    result = {}

    if over:
        result["over25"] = max(over)

    if under:
        result["under25"] = max(under)

    return result


def _extract_odds(
    event: dict,
    home: str,
    away: str,
) -> dict:
    odds = {}

    odds.update(
        _choose_best_h2h(
            event,
            home,
            away,
        )
    )

    odds.update(
        _choose_totals(event)
    )

    return odds


def _attach_odds(fixtures: list[dict]) -> dict:
    """Attach The Odds API market odds to existing fixtures.

    No odds are invented.
    Fixtures without a matching Odds API event retain {} odds.
    """

    if not ODDS_API_KEY:
        return {
            "enabled": False,
            "matched": 0,
            "events": 0,
            "notes": ["ODDS_API_IO_KEY is not configured"],
        }

    groups: dict[str, list[dict]] = {}

    for fx in fixtures:
        sport_key = _sport_key_for_fixture(fx)

        if sport_key:
            groups.setdefault(
                sport_key,
                [],
            ).append(fx)

    matched = 0
    total_events = 0
    errors = []

    for sport_key, group in groups.items():
        try:
            events = _odds_api_get(sport_key)

            total_events += len(events)

        except Exception as exc:
            errors.append(
                f"{sport_key}: {exc}"
            )
            continue

        for fx in group:
            home = _norm_name(fx.get("home"))
            away = _norm_name(fx.get("away"))

            if not home or not away:
                continue

            best_event = None

            for event in events:
                event_home = _norm_name(
                    event.get("home_team")
                )
                event_away = _norm_name(
                    event.get("away_team")
                )

                if (
                    event_home == home
                    and event_away == away
                ):
                    best_event = event
                    break

            if best_event is None:
                continue

            odds = _extract_odds(
                best_event,
                fx.get("home"),
                fx.get("away"),
            )

            if odds:
                fx["odds"] = odds
                fx["odds_source"] = "the-odds-api"
                fx["odds_event_id"] = best_event.get("id")
                matched += 1

    return {
        "enabled": True,
        "matched": matched,
        "events": total_events,
        "groups": len(groups),
        "notes": errors,
    }


# ============================================================
# FIXTURE NORMALIZATION
# ============================================================

def _norm_fx(row: dict, league=None) -> dict:
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
        "id": str(
            row.get("id")
            or row.get("event_id")
            or ""
        ),
        "home": home,
        "away": away,
        "kickoff": kickoff,
        "league": league_value,
        "leagueName": (
            row.get("leagueName")
            or row.get("league_name")
        ),
        "sport_key": row.get("sport_key"),
        "status": status,
        "minute": (
            row.get("current_minute")
            or row.get("matchElapsed")
        ),
        "home_score": home_score,
        "away_score": away_score,
        "odds": {},
        "source": row.get("source") or "goaldir",
        "raw": row,
    }


# ============================================================
# CAPTURE
# ============================================================

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
                        r.get("id")
                        or r.get("event_id")
                        or ""
                    ),
                    "raw": r,
                })

            # Goaldir enrichment is now for lineups/data only.
            try:
                gd.enrich_imminent(
                    blob.get("fixtures") or []
                )
            except Exception:
                pass

            api_calls = (
                blob.get("api_calls_today")
                or 0
            )

            sources.append("goaldir")

        except Exception as e:
            notes.append(
                f"Goaldir: {e}"
            )

    else:
        notes.append(
            "GOALDIR_API_KEY yok — ESPN yedeği."
        )

    # ---------------------------------------------------------
    # ESPN FALLBACK
    # ---------------------------------------------------------

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
    # REAL MARKET ODDS
    # ---------------------------------------------------------

    odds_report = _attach_odds(fixtures)

    if odds_report["enabled"]:
        sources.append("the-odds-api")

    notes.extend(
        odds_report.get("notes") or []
    )

    # ---------------------------------------------------------
    # MODEL PREDICTIONS
    # ---------------------------------------------------------

    preds = [
        predict_match(fx, book)
        for fx in fixtures
        if fx.get("home")
        and fx.get("away")
    ]

    # ---------------------------------------------------------
    # PREDICTION LIST
    # ---------------------------------------------------------

    picks = [
        p
        for p in preds
        if (
            p.get("pick")
            and p["pick"].get("decision")
            in {
                "STRONG",
                "CANDIDATE",
                "WATCH",
            }
        )
    ]

    # ---------------------------------------------------------
    # SAVE PREDICTIONS / PAPER BETS
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
            "payload": json.dumps(
                p,
                default=str,
            ),
        })

        if (
            pick.get("decision")
            in {
                "STRONG",
                "CANDIDATE",
                "WATCH",
            }
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
                "payload": json.dumps(
                    p,
                    default=str,
                ),
            })

    # ---------------------------------------------------------
    # BACKTEST
    # ---------------------------------------------------------

    try:
        bt = walk_forward(hist)
    except Exception as e:
        bt = {
            "error": str(e)
        }

    # ---------------------------------------------------------
    # REPORT
    # ---------------------------------------------------------

    report = {
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "history_matches": int(len(hist)),
        "fixtures": len(fixtures),
        "predictions": len(preds),
        "picks": picks,
        "all": preds,
        "sources": sources,
        "notes": notes,
        "goaldir": bool(GOALDIR_KEY),
        "odds_api": odds_report,
        "api_calls_today": api_calls,
        "backtest": bt,
    }

    REPORTS.mkdir(
        parents=True,
        exist_ok=True,
    )

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
        "odds_api": odds_report,
        "api_calls_today": api_calls,
        "notes": notes,
        "report": str(
            REPORTS / "latest.json"
        ),
    }
