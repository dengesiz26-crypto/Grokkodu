from __future__ import annotations
import numpy as np
import pandas as pd


def infer_columns(df: pd.DataFrame):
    skip = ("result", "target", "outcome", "home", "away", "date", "season", "score", "league", "name")
    out = []
    for c in df.columns:
        lc = c.lower()
        if any(x in lc for x in skip):
            continue
        if pd.api.types.is_numeric_dtype(df[c]):
            out.append(c)
    return out


def add_targets(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    if "home_goals" not in x.columns and "home_score" in x.columns:
        x["home_goals"] = x["home_score"]
    if "away_goals" not in x.columns and "away_score" in x.columns:
        x["away_goals"] = x["away_score"]
    if "result" not in x.columns and {"home_goals", "away_goals"} <= set(x.columns):
        x["result"] = np.select([x.home_goals > x.away_goals, x.home_goals == x.away_goals], [0, 1], default=2)
    if "ou25" not in x.columns and {"home_goals", "away_goals"} <= set(x.columns):
        x["ou25"] = ((x.home_goals + x.away_goals) > 2.5).astype(int)
    if "btts" not in x.columns and {"home_goals", "away_goals"} <= set(x.columns):
        x["btts"] = ((x.home_goals > 0) & (x.away_goals > 0)).astype(int)
    return x
