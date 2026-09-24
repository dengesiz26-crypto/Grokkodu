from __future__ import annotations
import json
from .db import connect, init


def record(c: dict):
    init()
    con = connect()
    con.execute(
        "INSERT INTO paper_bets(created_at,match_key,phase,market,selection,odds,probability,stake,status,payload) VALUES(datetime('now'),?,?,?,?,?,?,?,?,'OPEN',?)",
        (c["match_key"], c.get("phase", "pre"), c["market"], c.get("selection", c["market"]), c["odds"], c["probability"], c.get("stake", 1), json.dumps(c)),
    )
    con.commit()
    con.close()
