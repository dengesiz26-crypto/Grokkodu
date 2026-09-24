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


def _team_name(value):
    if isinstance(value, dict):
        return (
            value.get("name")
            or value.get("short_name")
            or value.get("id")
        )

    return value


def _result_key(row):
    home = _team_name(
        row.get("home_team")
        or row.get("homeTeam")
        or row.get("home")
        or row.get("homeTeamName")
    )

    away = _team_name(
        row.get("away_team")
        or row.get("awayTeam")
        or row.get("away")
        or row.get("awayTeamName")
    )

    if not home or not away:
        return None

    return f"{home}|{away}"


def _result_score(row):
    hg = (
        row.get("home_score")
        if row.get("home_score") is not None
        else row.get("homeTeamScore")
    )

    ag = (
        row.get("away_score")
        if row.get("away_score") is not None
        else row.get("awayTeamScore")
    )

    try:
        return float(hg), float(ag)
    except (TypeError, ValueError):
        return None


def _build_performance(c):
    total = c.execute(
        "SELECT COUNT(*) FROM paper_bets"
    ).fetchone()[0]

    settled = c.execute(
        """
        SELECT COUNT(*)
        FROM paper_bets
        WHERE status IN ('WON', 'LOST')
        """
    ).fetchone()[0]

    won = c.execute(
        """
        SELECT COUNT(*)
        FROM paper_bets
        WHERE status = 'WON'
        """
    ).fetchone()[0]

    lost = c.execute(
        """
        SELECT COUNT(*)
        FROM paper_bets
        WHERE status = 'LOST'
        """
    ).fetchone()[0]

    open_count = c.execute(
        """
        SELECT COUNT(*)
        FROM paper_bets
        WHERE status = 'OPEN'
        """
    ).fetchone()[0]

    pnl_row = c.execute(
        """
        SELECT COALESCE(SUM(pnl), 0)
        FROM paper_bets
        WHERE status IN ('WON', 'LOST')
        """
    ).fetchone()

    pnl = float(pnl_row[0] or 0.0)

    hit_rate = (
        (won / settled) * 100
        if settled > 0
        else 0.0
    )

    by_market_rows = c.execute(
        """
        SELECT
            market,
            COUNT(*) AS total,
            SUM(CASE WHEN status = 'WON' THEN 1 ELSE 0 END) AS won,
            SUM(CASE WHEN status = 'LOST' THEN 1 ELSE 0 END) AS lost,
            SUM(CASE WHEN status = 'OPEN' THEN 1 ELSE 0 END) AS open,
            COALESCE(SUM(
                CASE
                    WHEN status IN ('WON', 'LOST')
                    THEN pnl
                    ELSE 0
                END
            ), 0) AS pnl
        FROM paper_bets
        GROUP BY market
        ORDER BY total DESC
        """
    ).fetchall()

    by_market = {}

    for row in by_market_rows:
        market_total = int(row["total"] or 0)
        market_won = int(row["won"] or 0)
        market_lost = int(row["lost"] or 0)
        market_settled = market_won + market_lost

        by_market[row["market"]] = {
            "total": market_total,
            "settled": market_settled,
            "won": market_won,
            "lost": market_lost,
            "open": int(row["open"] or 0),
            "hit_rate": (
                round(
                    (market_won / market_settled) * 100,
                    2,
                )
                if market_settled > 0
                else 0.0
            ),
            "pnl": round(
                float(row["pnl"] or 0.0),
                4,
            ),
        }

    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total": int(total),
        "settled": int(settled),
        "open": int(open_count),
        "won": int(won),
        "lost": int(lost),
        "hit_rate": round(hit_rate, 2),
        "pnl": round(pnl, 4),
        "by_market": by_market,
    }


def settle() -> dict:
    init()

    results = {}

    # ---------------------------------------------------------
    # GOALDIR / BSD V2
    # ---------------------------------------------------------
    if GOALDIR_KEY:
        try:
            goaldir_results = Goaldir().results_yesterday()

            for r in goaldir_results:
                key = _result_key(r)
                score = _result_score(r)

                if key and score is not None:
                    results[key] = score

        except Exception:
            pass

    # ---------------------------------------------------------
    # ESPN FALLBACK
    # ---------------------------------------------------------
    try:
        for e in scoreboard():
            status = (
                e.get("matchStatus")
                or e.get("status")
                or ""
            )

            if str(status).lower() not in {
                "finished",
                "complete",
                "completed",
            }:
                continue

            key = _result_key(e)
            score = _result_score(e)

            if key and score is not None:
                results[key] = score

    except Exception:
        pass

    c = connect()

    open_bets = list(
        c.execute(
            """
            SELECT
                id,
                match_key,
                market,
                odds,
                probability
            FROM paper_bets
            WHERE status = 'OPEN'
            """
        )
    )

    settled = 0
    pnl = 0.0

    now = datetime.now(timezone.utc).isoformat()

    for row in open_bets:
        mk = row["match_key"]

        score = None

        # match_key format:
        # kickoff|home|away
        if "|" in mk:
            parts = mk.split("|")

            if len(parts) >= 3:
                home = parts[-2]
                away = parts[-1]

                direct_key = f"{home}|{away}"
                score = results.get(direct_key)

                # Fallback: normalize whitespace/case.
                if score is None:
                    for result_key, result_score in results.items():
                        result_parts = result_key.split("|")

                        if len(result_parts) != 2:
                            continue

                        rh, ra = result_parts

                        if (
                            rh.strip().lower()
                            == home.strip().lower()
                            and
                            ra.strip().lower()
                            == away.strip().lower()
                        ):
                            score = result_score
                            break

        if score is None:
            continue

        hg, ag = score

        won = _won(
            row["market"],
            hg,
            ag,
        )

        odds = float(row["odds"])

        delta = (
            odds - 1.0
            if won
            else -1.0
        )

        c.execute(
            """
            UPDATE paper_bets
            SET
                status = ?,
                settled_at = ?,
                pnl = ?
            WHERE id = ?
            """,
            (
                "WON" if won else "LOST",
                now,
                delta,
                row["id"],
            ),
        )

        settled += 1
        pnl += delta

    c.commit()

    # ---------------------------------------------------------
    # PERMANENT PERFORMANCE HISTORY
    # ---------------------------------------------------------
    performance = _build_performance(c)

    c.close()

    summary = {
        "settled_now": settled,
        "pnl_now": round(pnl, 4),
        "open_checked": len(open_bets),
        "performance": performance,
    }

    REPORTS.mkdir(parents=True, exist_ok=True)

    # Last settlement run
    (REPORTS / "settlement.json").write_text(
        json.dumps(
            summary,
            indent=2,
            default=str,
        )
    )

    # Current complete performance snapshot.
    # This file is intentionally overwritten every run.
    (REPORTS / "performance.json").write_text(
        json.dumps(
            performance,
            indent=2,
            default=str,
        )
    )

    return {
        "settled": settled,
        "pnl": round(pnl, 4),
        "open_checked": len(open_bets),
        "total": performance["total"],
        "won": performance["won"],
        "lost": performance["lost"],
        "settled_total": performance["settled"],
        "hit_rate": performance["hit_rate"],
        "total_pnl": performance["pnl"],
    }
