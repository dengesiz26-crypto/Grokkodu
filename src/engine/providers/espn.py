from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from ..config import load_leagues

UA = {"User-Agent": "KALE-Engine/2.0", "Accept": "application/json"}


def _ml(ml):
    if ml is None:
        return None
    try:
        ml = float(ml)
    except Exception:
        return None
    if ml == 0:
        return None
    return 1 + ml / 100 if ml > 0 else 1 + 100 / abs(ml)


def _league(espn: str) -> list[dict]:
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{espn}/scoreboard"
    try:
        r = requests.get(url, headers=UA, timeout=18)
        if r.status_code != 200:
            return []
        data = r.json()
    except Exception:
        return []
    out = []
    for e in data.get("events") or []:
        comp = (e.get("competitions") or [{}])[0]
        teams = comp.get("competitors") or []
        home = next((t for t in teams if t.get("homeAway") == "home"), None)
        away = next((t for t in teams if t.get("homeAway") == "away"), None)
        if not home or not away:
            continue
        st = ((e.get("status") or {}).get("type") or {}).get("state")
        status = {"pre": "scheduled", "in": "live", "post": "finished"}.get(st, "unknown")
        odd = (comp.get("odds") or [None])[0] or {}
        out.append({
            "id": f"espn:{espn}:{e.get('id')}",
            "kickoffUtc": e.get("date"),
            "homeTeamName": ((home.get("team") or {}).get("displayName")),
            "awayTeamName": ((away.get("team") or {}).get("displayName")),
            "homeTeamScore": home.get("score"),
            "awayTeamScore": away.get("score"),
            "matchStatus": status,
            "matchElapsed": None,
            "leagueEspn": espn,
            "odds": {
                "home": _ml(((odd.get("homeTeamOdds") or {}).get("moneyLine"))),
                "draw": _ml(((odd.get("drawOdds") or {}).get("moneyLine"))),
                "away": _ml(((odd.get("awayTeamOdds") or {}).get("moneyLine"))),
            },
            "source": "espn",
        })
    return out


def scoreboard() -> list[dict]:
    codes = [lg["espn"] for lg in load_leagues()["leagues"] if lg.get("espn")]
    out = []
    with ThreadPoolExecutor(10) as ex:
        futs = [ex.submit(_league, c) for c in codes]
        for f in as_completed(futs):
            try:
                out.extend(f.result())
            except Exception:
                pass
    return out
