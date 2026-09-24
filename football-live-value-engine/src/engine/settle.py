from __future__ import annotations
import json
from datetime import datetime, timezone
from .db import connect, init
from .providers.goaldir import Goaldir
from .providers.espn import scoreboard
from .config import GOALDIR_KEY, REPORTS


def _won(market, hg, ag) -> bool:
    if market == "home":
        return hg > ag
    if market == "draw":
        return hg == ag
    if market == "away":
        return hg < ag
    if market == "over25":
        return hg + ag > 2.5
    if market == "under25":
        return hg + ag < 2.5
    if market == "btts_yes":
        return hg > 0 and ag > 0
    if market == "btts_no":
        return not (hg > 0 and ag > 0)
    return False


def settle() -> dict:
    init()
    results = {}
    if GOALDIR_KEY:
        for r in Goaldir().results_yesterday():
            key = f"{r.get('homeTeamName')}|{r.get('awayTeamName')}"
            try:
                results[key] = (float(r.get("homeTeamScore")), float(r.get("awayTeamScore")))
            except Exception:
                pass
    for e in scoreboard():
        if e.get("matchStatus") != "finished":
            continue
        key = f"{e.get('homeTeamName')}|{e.get('awayTeamName')}"
        try:
            results[key] = (float(e.get("homeTeamScore") or 0), float(e.get("awayTeamScore") or 0))
        except Exception:
            pass
    c = connect()
    open_bets = list(c.execute("SELECT id, match_key, market, odds, probability FROM paper_bets WHERE status='OPEN'"))
    settled = 0
    pnl = 0.0
    now = datetime.now(timezone.utc).isoformat()
    for row in open_bets:
        mk = row["match_key"]
        homeaway = None
        if "|" in mk:
            parts = mk.split("|")
            homeaway = f"{parts[-2]}|{parts[-1]}" if len(parts) >= 2 else None
        score = results.get(homeaway) if homeaway else None
        if score is None:
            for k, v in results.items():
                if k.split("|")[0] in mk and k.split("|")[-1] in mk:
                    score = v
                    break
        if score is None:
            continue
        hg, ag = score
        won = _won(row["market"], hg, ag)
        delta = (row["odds"] - 1) if won else -1
        c.execute(
            "UPDATE paper_bets SET status=?, settled_at=?, pnl=? WHERE id=?",
            ("WON" if won else "LOST", now, delta, row["id"]),
        )
        settled += 1
        pnl += delta
    c.commit()
    c.close()
    summary = {"settled": settled, "pnl": pnl, "open_checked": len(open_bets)}
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "settlement.json").write_text(json.dumps(summary, indent=2))
    return summary
