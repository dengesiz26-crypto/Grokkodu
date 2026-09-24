from __future__ import annotations
import io
import pandas as pd
import requests
from ..config import RAW, load_leagues

UA = {"User-Agent": "KALE-Engine/2.0"}


def _get(url: str) -> str | None:
    r = requests.get(url, headers=UA, timeout=40)
    if r.status_code != 200 or len(r.content) < 80:
        return None
    text = r.content.decode("utf-8-sig", errors="replace")
    if "HomeTeam" not in text[:500] and "Home," not in text[:500]:
        return None
    return text


def download_history() -> pd.DataFrame:
    cfg = load_leagues()
    seasons = cfg["seasons"]
    frames = []
    RAW.mkdir(parents=True, exist_ok=True)
    for lg in cfg["leagues"]:
        if lg.get("fduk"):
            for season in seasons:
                url = f"https://www.football-data.co.uk/mmz4281/{season}/{lg['fduk']}.csv"
                path = RAW / f"{season}_{lg['fduk']}.csv"
                text = None
                if path.exists() and path.stat().st_size > 80:
                    text = path.read_text(encoding="utf-8", errors="replace")
                else:
                    text = _get(url)
                    if text:
                        path.write_text(text, encoding="utf-8")
                if not text:
                    continue
                df = pd.read_csv(io.StringIO(text))
                df["league_id"] = lg["id"]
                df["league_name"] = f"{lg['country']} {lg['name']}"
                frames.append(df)
        elif lg.get("fdukNew"):
            url = f"https://www.football-data.co.uk/new/{lg['fdukNew']}.csv"
            path = RAW / f"new_{lg['fdukNew']}.csv"
            text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else _get(url)
            if text:
                path.write_text(text, encoding="utf-8")
                df = pd.read_csv(io.StringIO(text))
                df["league_id"] = lg["id"]
                df["league_name"] = f"{lg['country']} {lg['name']}"
                frames.append(df)
    if not frames:
        raise RuntimeError("No historical CSVs downloaded from football-data.co.uk")
    df = pd.concat(frames, ignore_index=True, sort=False)
    return normalize(df)


def _parse_date(s):
    return pd.to_datetime(s, dayfirst=True, errors="coerce")


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    x["date"] = _parse_date(x["Date"]) if "Date" in x.columns else pd.NaT
    home = x["HomeTeam"] if "HomeTeam" in x.columns else x.get("Home")
    away = x["AwayTeam"] if "AwayTeam" in x.columns else x.get("Away")
    hg = x["FTHG"] if "FTHG" in x.columns else x.get("HG")
    ag = x["FTAG"] if "FTAG" in x.columns else x.get("AG")
    out = pd.DataFrame({
        "date": x["date"],
        "league": x.get("league_id", "unk"),
        "league_name": x.get("league_name", ""),
        "home": home,
        "away": away,
        "home_goals": pd.to_numeric(hg, errors="coerce"),
        "away_goals": pd.to_numeric(ag, errors="coerce"),
        "hxg": pd.to_numeric(x["HxG"], errors="coerce") if "HxG" in x.columns else None,
        "axg": pd.to_numeric(x["AxG"], errors="coerce") if "AxG" in x.columns else None,
        "odds_h": _first(x, ["AvgH", "PSH", "B365H", "PH"]),
        "odds_d": _first(x, ["AvgD", "PSD", "B365D", "PD"]),
        "odds_a": _first(x, ["AvgA", "PSA", "B365A", "PA"]),
        "odds_over": _first(x, ["Avg>2.5", "P>2.5", "B365>2.5"]),
        "odds_under": _first(x, ["Avg<2.5", "P<2.5", "B365<2.5"]),
        "close_h": _first(x, ["AvgCH", "PSCH", "B365CH"]),
        "close_d": _first(x, ["AvgCD", "PSCD", "B365CD"]),
        "close_a": _first(x, ["AvgCA", "PSCA", "B365CA"]),
    })
    out = out.dropna(subset=["date", "home", "away", "home_goals", "away_goals"])
    out["result"] = 0
    out.loc[out.home_goals == out.away_goals, "result"] = 1
    out.loc[out.home_goals < out.away_goals, "result"] = 2
    out["ou25"] = (out.home_goals + out.away_goals > 2.5).astype(int)
    out["btts"] = ((out.home_goals > 0) & (out.away_goals > 0)).astype(int)
    return out.sort_values("date").reset_index(drop=True)


def _first(df: pd.DataFrame, cols: list[str]):
    for c in cols:
        if c in df.columns:
            return pd.to_numeric(df[c], errors="coerce")
    return pd.Series([None] * len(df))
