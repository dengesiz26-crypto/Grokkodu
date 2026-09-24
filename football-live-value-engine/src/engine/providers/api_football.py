"""Optional API-Football fallback. Goaldir is primary."""
from __future__ import annotations
import time, requests
from ..config import API_FOOTBALL_KEY

BASE = "https://v3.football.api-sports.io"


class APIFootball:
    def __init__(self, key=None, interval=6.2):
        self.key = key or API_FOOTBALL_KEY
        self.interval = interval
        self.last = 0

    def get(self, path, params=None):
        if not self.key:
            raise RuntimeError("API_FOOTBALL_KEY is not configured")
        wait = self.interval - (time.time() - self.last)
        if wait > 0:
            time.sleep(wait)
        r = requests.get(BASE + "/" + path.lstrip("/"), params=params or {}, headers={"x-apisports-key": self.key}, timeout=30)
        self.last = time.time()
        r.raise_for_status()
        d = r.json()
        if d.get("errors"):
            raise RuntimeError(str(d["errors"]))
        return d

    def fixtures_live(self):
        return self.get("fixtures", {"live": "all"})

    def fixture_statistics(self, fixture_id):
        return self.get("fixtures/statistics", {"fixture": fixture_id})

    def fixture_lineups(self, fixture_id):
        return self.get("fixtures/lineups", {"fixture": fixture_id})

    def fixture_events(self, fixture_id):
        return self.get("fixtures/events", {"fixture": fixture_id})
