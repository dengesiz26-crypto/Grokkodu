from __future__ import annotations
import math
import pandas as pd

HALF_LIFE = 160
XI = math.log(2) / HALF_LIFE
K_ELO = 18
HOME_ELO = 62


def _fold(s: str) -> str:
    return "".join(ch for ch in str(s).lower() if ch.isalnum() or ch.isspace()).split()


def fold_name(s: str) -> str:
    toks = [t for t in _fold(s) if t not in {"fc", "cf", "afc", "sc", "fk", "sk", "ac", "cd", "ud"}]
    return " ".join(toks)


def build_ratings(df: pd.DataFrame, as_of=None) -> dict:
    df = df.dropna(subset=["date", "home", "away", "home_goals", "away_goals"]).sort_values("date")
    end = pd.Timestamp(as_of) if as_of is not None else df["date"].max()
    teams: dict[str, dict] = {}
    league = {}

    def team(name):
        k = fold_name(name)
        if k not in teams:
            teams[k] = {
                "name": name, "elo": 1500.0,
                "h_att": 1.0, "h_def": 1.0, "a_att": 1.0, "a_def": 1.0,
                "played": 0.0, "form": [], "btts": 0.0, "ou": 0.0, "wn": 0.0,
            }
        return teams[k]

    for _, m in df.iterrows():
        days = abs((end - pd.Timestamp(m["date"])).days)
        w = math.exp(-XI * days)
        lg = m["league"]
        s = league.setdefault(lg, {"h": 0.0, "a": 0.0, "n": 0.0, "name": m.get("league_name", lg)})
        s["h"] += float(m.home_goals) * w
        s["a"] += float(m.away_goals) * w
        s["n"] += w

    for lg, s in league.items():
        n = max(s["n"], 1)
        s["avg_h"] = s["h"] / n
        s["avg_a"] = s["a"] / n

    for _, m in df.iterrows():
        days = abs((end - pd.Timestamp(m["date"])).days)
        w = math.exp(-XI * days)
        h, a = team(m.home), team(m.away)
        exp = 1 / (1 + 10 ** ((a["elo"] - (h["elo"] + HOME_ELO)) / 400))
        actual = 1.0 if m.home_goals > m.away_goals else 0.5 if m.home_goals == m.away_goals else 0.0
        k = K_ELO * (0.6 + 0.4 * w)
        h["elo"] += k * (actual - exp)
        a["elo"] += k * (exp - actual)
        lg = league.get(m.league, {"avg_h": 1.45, "avg_a": 1.15})
        lr = 0.12 * w
        hg, ag = float(m.home_goals), float(m.away_goals)
        h["h_att"] += lr * (hg / max(0.4, lg["avg_h"] * a["a_def"]) - 1)
        a["a_def"] += lr * (hg / max(0.4, lg["avg_h"] * h["h_att"]) - 1)
        a["a_att"] += lr * (ag / max(0.4, lg["avg_a"] * h["h_def"]) - 1)
        h["h_def"] += lr * (ag / max(0.4, lg["avg_a"] * a["a_att"]) - 1)
        h["played"] += w
        a["played"] += w
        h["form"].append(1 if actual == 1 else 0.33 if actual == 0.5 else 0)
        a["form"].append(1 if actual == 0 else 0.33 if actual == 0.5 else 0)
        h["form"] = h["form"][-8:]
        a["form"] = a["form"][-8:]
        btts = 1 if hg > 0 and ag > 0 else 0
        ou = 1 if hg + ag > 2.5 else 0
        for t in (h, a):
            t["btts"] += btts * w
            t["ou"] += ou * w
            t["wn"] += w

    for t in teams.values():
        for k in ("h_att", "h_def", "a_att", "a_def"):
            t[k] = min(2.4, max(0.4, t[k]))
        t["form_n"] = sum(t["form"]) / len(t["form"]) if t["form"] else 0.45
        t["btts_r"] = t["btts"] / t["wn"] if t["wn"] else 0.52
        t["ou_r"] = t["ou"] / t["wn"] if t["wn"] else 0.52

    return {"teams": teams, "leagues": league, "as_of": str(end.date())}


def lookup(book: dict, name: str):
    k = fold_name(name)
    t = book["teams"].get(k)
    if t:
        return t
    for key, val in book["teams"].items():
        if k and (k in key or key in k) and min(len(k), len(key)) >= 4:
            return val
    return None
