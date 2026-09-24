from __future__ import annotations
import math
import pandas as pd
from .ratings import build_ratings
from .predict import predict_match


def walk_forward(df: pd.DataFrame, train_frac=0.82) -> dict:
    df = df.dropna(subset=["date", "home", "away", "home_goals", "away_goals"]).sort_values("date")
    if len(df) < 400:
        return {"n": int(len(df)), "note": "insufficient"}
    cut = int(len(df) * train_frac)
    train, test = df.iloc[:cut], df.iloc[cut:]
    book = build_ratings(train, as_of=train["date"].max())
    n = correct = brier = logloss = 0.0
    stake = pnl = pick_n = pick_hit = 0.0
    for _, m in test.iterrows():
        fx = {
            "home": m.home, "away": m.away, "league": m.league, "status": "scheduled",
            "odds": {"home": m.get("odds_h"), "draw": m.get("odds_d"), "away": m.get("odds_a"),
                     "over25": m.get("odds_over"), "under25": m.get("odds_under")},
        }
        p = predict_match(fx, book)
        mk = {q["market"]: q["probability"] for q in p["markets"]}
        y = 0 if m.home_goals > m.away_goals else 1 if m.home_goals == m.away_goals else 2
        ph, pd_, pa = mk["home"], mk["draw"], mk["away"]
        pred = 0 if ph >= pd_ and ph >= pa else 1 if pd_ >= pa else 2
        n += 1
        correct += pred == y
        yh, yd, ya = (y == 0), (y == 1), (y == 2)
        brier += (ph - yh) ** 2 + (pd_ - yd) ** 2 + (pa - ya) ** 2
        py = [ph, pd_, pa][y]
        logloss += -math.log(max(py, 1e-6))
        pick = p.get("pick")
        if pick and pick["decision"] in {"STRONG", "CANDIDATE"} and pick.get("market_odds"):
            won = False
            if pick["market"] == "home":
                won = y == 0
            elif pick["market"] == "draw":
                won = y == 1
            elif pick["market"] == "away":
                won = y == 2
            elif pick["market"] == "over25":
                won = (m.home_goals + m.away_goals) > 2.5
            elif pick["market"] == "under25":
                won = (m.home_goals + m.away_goals) < 2.5
            elif pick["market"] == "btts_yes":
                won = m.home_goals > 0 and m.away_goals > 0
            elif pick["market"] == "btts_no":
                won = not (m.home_goals > 0 and m.away_goals > 0)
            stake += 1
            pick_n += 1
            pnl += (pick["market_odds"] - 1) if won else -1
            pick_hit += int(won)
    return {
        "n": int(n),
        "accuracy1x2": correct / n if n else 0,
        "brier": brier / n if n else 0,
        "log_loss": logloss / n if n else 0,
        "picks": int(pick_n),
        "hit_rate": pick_hit / pick_n if pick_n else 0,
        "roi": pnl / stake if stake else 0,
    }
