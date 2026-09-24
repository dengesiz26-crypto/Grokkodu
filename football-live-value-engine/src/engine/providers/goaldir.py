"""Goaldir / GOAL API — fixtures, results, odds, lineups, live.

NEVER call /predictions. That page is not our model.
"""
from __future__ import annotations
from datetime import date, timedelta
from typing import Any
from ..config import GOALDIR_BASE, GOALDIR_KEY, LINEUP_HORIZON_HOURS, LINEUP_MAX_PER_RUN
from ..http import cached_get, budget_today

PREDICTION_PATHS = ("/predictions", "/prediction")


class Goaldir:
    def __init__(self, key: str | None = None):
        self.key = (key or GOALDIR_KEY).strip()
        self.base = GOALDIR_BASE

    @property
    def enabled(self) -> bool:
        return bool(self.key)

    def _get(self, path: str, ttl: int) -> Any:
        if not self.enabled:
            raise RuntimeError("GOALDIR_API_KEY missing — live bulletin will use ESPN fallback, nothing is fabricated")
        if any(x in path.lower() for x in PREDICTION_PATHS):
            raise RuntimeError("Blocked: Goaldir prediction endpoints are not used by KALE")
        url = self.base + "/" + path.lstrip("/")
        return cached_get(
            url,
            headers={"Authorization": f"Bearer {self.key}"},
            ttl=ttl,
            provider="goaldir",
        )

    def _data(self, path: str, ttl: int) -> list[dict]:
        body = self._get(path, ttl)
        if isinstance(body, list):
            return body
        if isinstance(body, dict):
            if isinstance(body.get("data"), list):
                return body["data"]
            if isinstance(body.get("items"), list):
                return body["items"]
        return []

    def fixtures_date(self, d: date) -> list[dict]:
        return self._data(f"fixtures/date/{d.isoformat()}", ttl=3 * 3600)

    def fixtures_live(self) -> list[dict]:
        return self._data("fixtures/live", ttl=90)

    def results_date(self, d: date) -> list[dict]:
        return self._data(f"results/date/{d.isoformat()}", ttl=4 * 3600)

    def results_yesterday(self) -> list[dict]:
        return self._data("results/yesterday", ttl=4 * 3600)

    def fixture_odds(self, fixture_id: str) -> list[dict]:
        return self._data(f"fixtures/{fixture_id}/odds", ttl=2 * 3600)

    def fixture_lineups(self, fixture_id: str) -> Any:
        return self._get(f"fixtures/{fixture_id}/lineups", ttl=3 * 3600)

    def fixture_stats(self, fixture_id: str) -> Any:
        return self._get(f"fixtures/{fixture_id}/statistics", ttl=120)

    def fixture_events(self, fixture_id: str) -> Any:
        return self._get(f"fixtures/{fixture_id}/events", ttl=60)

    def capture_bulletin(self) -> dict:
        """2–4×/day capture: date windows + one live snapshot. No per-match spam."""
        today = date.today()
        tomorrow = today + timedelta(days=1)
        yesterday = today - timedelta(days=1)
        fixtures = self.fixtures_date(today) + self.fixtures_date(tomorrow)
        results = self.results_yesterday() or self.results_date(yesterday)
        live = self.fixtures_live()
        return {
            "fixtures": fixtures,
            "results": results,
            "live": live,
            "api_calls_today": budget_today("goaldir"),
        }

    def enrich_imminent(self, fixtures: list[dict], now_iso_kickoff_key="kickoffUtc") -> list[dict]:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        scored = []
        for fx in fixtures:
            raw = fx.get(now_iso_kickoff_key) or fx.get("kickoff") or ""
            try:
                t = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            except Exception:
                continue
            hours = (t - now).total_seconds() / 3600
            if -0.25 <= hours <= LINEUP_HORIZON_HOURS:
                scored.append((hours, fx))
        scored.sort(key=lambda x: x[0])
        out = []
        for _, fx in scored[:LINEUP_MAX_PER_RUN]:
            fid = str(fx.get("id") or "")
            if not fid:
                continue
            try:
                if not fx.get("odds"):
                    fx["odds"] = self.fixture_odds(fid)
                fx["lineups"] = self.fixture_lineups(fid)
            except Exception:
                pass
            out.append(fx)
        return out
