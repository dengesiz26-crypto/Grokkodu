from __future__ import annotations

from .models.poisson import markets as pois_markets, live_markets
from .ratings import lookup
from .value import decide, value as value_of


def _clamp(p):
    return min(0.92, max(0.04, p))


def _elo_1x2(home_elo, away_elo):
    exp = 1 / (1 + 10 ** ((away_elo - (home_elo + 62)) / 400))
    closeness = 1 - abs(2 * exp - 1)
    draw = 0.22 + 0.14 * closeness
    home = exp * (1 - draw)
    away = (1 - exp) * (1 - draw)

    s = home + draw + away

    return home / s, draw / s, away / s


def predict_match(fx: dict, book: dict) -> dict:
    home = lookup(
        book,
        fx.get("home") or fx.get("homeTeamName") or "",
    )

    away = lookup(
        book,
        fx.get("away") or fx.get("awayTeamName") or "",
    )

    league_id = fx.get("league") or fx.get("league_id")

    lg = book["leagues"].get(
        league_id,
        {
            "avg_h": 1.45,
            "avg_a": 1.15,
        },
    )

    avg_h = lg.get("avg_h", 1.45)
    avg_a = lg.get("avg_a", 1.15)

    h_att = (home or {}).get("h_att", 1.0)
    h_def = (home or {}).get("h_def", 1.0)
    a_att = (away or {}).get("a_att", 1.0)
    a_def = (away or {}).get("a_def", 1.0)

    lam_h = min(
        3.8,
        max(
            0.35,
            avg_h * h_att * a_def,
        ),
    )

    lam_a = min(
        3.4,
        max(
            0.28,
            avg_a * a_att * h_def,
        ),
    )

    thin = (
        (home or {}).get("played", 0) < 6
        or
        (away or {}).get("played", 0) < 6
    )

    if thin:
        lam_h = (
            0.55 * lam_h
            + 0.45 * avg_h
        )

        lam_a = (
            0.55 * lam_a
            + 0.45 * avg_a
        )

    dc = pois_markets(
        lam_h,
        lam_a,
    )

    status = (
        fx.get("status")
        or fx.get("matchStatus")
        or ""
    ).lower()

    if status in {"live", "in"}:
        minute = float(
            fx.get("minute")
            or fx.get("matchElapsed")
            or 45
        )

        hs = int(
            float(
                fx.get("home_score")
                or fx.get("homeTeamScore")
                or 0
            )
        )

        as_ = int(
            float(
                fx.get("away_score")
                or fx.get("awayTeamScore")
                or 0
            )
        )

        dc.update(
            live_markets(
                lam_h,
                lam_a,
                minute,
                hs,
                as_,
            )
        )

    eh, ed, ea = _elo_1x2(
        (home or {}).get("elo", 1500),
        (away or {}).get("elo", 1500),
    )

    fh = (home or {}).get("form_n", 0.45)
    fa = (away or {}).get("form_n", 0.45)

    form_h = (
        0.38
        + 0.28 * fh
        - 0.16 * fa
    )

    form_a = (
        0.32
        + 0.28 * fa
        - 0.16 * fh
    )

    form_d = max(
        0.18,
        1 - form_h - form_a,
    )

    fs = (
        form_h
        + form_d
        + form_a
    )

    home_p = _clamp(
        0.58 * dc["home"]
        + 0.28 * eh
        + 0.14 * form_h / fs
    )

    away_p = _clamp(
        0.58 * dc["away"]
        + 0.28 * ea
        + 0.14 * form_a / fs
    )

    draw_p = _clamp(
        1 - home_p - away_p
    )

    over_p = _clamp(
        0.78 * dc["over25"]
        + 0.11 * (home or {}).get("ou_r", 0.5)
        + 0.11 * (away or {}).get("ou_r", 0.5)
    )

    btts_p = _clamp(
        0.75 * dc["btts_yes"]
        + 0.125 * (home or {}).get("btts_r", 0.5)
        + 0.125 * (away or {}).get("btts_r", 0.5)
    )

    odds = fx.get("odds") or {}

    if isinstance(odds, list) and odds:
        odds = (
            odds[0]
            if isinstance(odds[0], dict)
            else {}
        )

    quotes = []

    for market, p, odd_key in (
        ("home", home_p, "home"),
        ("draw", draw_p, "draw"),
        ("away", away_p, "away"),
        ("over25", over_p, "over25"),
        ("under25", 1 - over_p, "under25"),
        ("btts_yes", btts_p, "btts_yes"),
        ("btts_no", 1 - btts_p, "btts_no"),
    ):
        if market == "home":
            fallback_key = "odd1"
        elif market == "draw":
            fallback_key = "oddX"
        elif market == "away":
            fallback_key = "odd2"
        else:
            fallback_key = None

        o = odds.get(odd_key)

        if o is None and fallback_key:
            o = odds.get(fallback_key)

        try:
            o = (
                float(o)
                if o is not None
                else None
            )
        except Exception:
            o = None

        v = value_of(p, o)

        if not v:
            v = {
                "probability": p,
                "fair_odds": 1 / p,
                "edge": None,
                "ev": None,
            }

        quotes.append(
            {
                "market": market,
                "probability": p,
                "fair_odds": v["fair_odds"],
                "market_odds": o,
                "edge": v.get("edge"),
                "ev": v.get("ev"),
                "decision": decide(p, o),
            }
        )

    decision_rank = {
        "STRONG": 3,
        "CANDIDATE": 2,
        "WATCH": 1,
        "ABSTAIN": 0,
    }

    ranked = sorted(
        quotes,
        key=lambda q: (
            decision_rank.get(
                q.get("decision"),
                0,
            ),
            q.get("probability") or 0,
            q.get("ev") or -9,
        ),
        reverse=True,
    )

    # Best market with a non-ABSTAIN decision.
    value_pick = next(
        (
            q
            for q in ranked
            if q.get("decision") != "ABSTAIN"
        ),
        None,
    )

    # Highest-probability model prediction regardless
    # of value decision.
    prediction_pick = max(
        quotes,
        key=lambda q: q.get("probability") or 0,
        default=None,
    )

    # Keep value pick when available.
    # Otherwise retain the model's highest-probability
    # prediction instead of returning None.
    pick = value_pick or prediction_pick

    return {
        "home": (
            fx.get("home")
            or fx.get("homeTeamName")
        ),
        "away": (
            fx.get("away")
            or fx.get("awayTeamName")
        ),
        "kickoff": (
            fx.get("kickoff")
            or fx.get("kickoffUtc")
        ),
        "league": league_id,
        "status": status,
        "lambda_home": lam_h,
        "lambda_away": lam_a,
        "most_likely": dc.get("most_likely"),
        "markets": quotes,
        "pick": pick,
        "value_pick": value_pick,
        "prediction_pick": prediction_pick,
        "missing_home": home is None,
        "missing_away": away is None,
        "model": "dixon-coles+elo+form",
    }
