"""Goaldir / BSD Football API v2 provider.

Uses the actively developed BSD Football API v2.

IMPORTANT:
- Uses Authorization: Token <API_KEY>
- Uses /api/v2/events/ endpoints
- NEVER calls /predictions/ or /events/{id}/prediction/
- Predictions must come from KALE's own model.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from ..config import (
    GOALDIR_BASE,
    GOALDIR_KEY,
    LINEUP_HORIZON_HOURS,
    LINEUP_MAX_PER_RUN,
)
from ..http import cached_get, budget_today


PREDICTION_PATHS = (
    "/predictions",
    "/prediction",
)


class Goaldir:
    """BSD / Goaldir Football API v2 client."""

    def __init__(self, key: str | None = None):
        self.key = (key or GOALDIR_KEY).strip()
        self.base = GOALDIR_BASE.rstrip("/")

    @property
    def enabled(self) -> bool:
        return bool(self.key)

    def _get(self, path: str, ttl: int) -> Any:
        """GET one BSD v2 endpoint."""

        if not self.enabled:
            raise RuntimeError(
                "GOALDIR_API_KEY missing — "
                "live bulletin will use ESPN fallback, "
                "nothing is fabricated"
            )

        normalized_path = "/" + path.lstrip("/")

        if any(
            blocked in normalized_path.lower()
            for blocked in PREDICTION_PATHS
        ):
            raise RuntimeError(
                "Blocked: Goaldir prediction endpoints are not used by KALE"
            )

        url = self.base + normalized_path

        return cached_get(
            url,
            headers={
                "Authorization": f"Token {self.key}",
            },
            ttl=ttl,
            provider="goaldir",
        )

    @staticmethod
    def _items(body: Any) -> list[dict]:
        """Normalize BSD paginated/list responses."""

        if isinstance(body, list):
            return body

        if not isinstance(body, dict):
            return []

        # BSD v2 paginated responses use "results".
        results = body.get("results")
        if isinstance(results, list):
            return results

        # Keep compatibility with possible provider wrappers.
        data = body.get("data")
        if isinstance(data, list):
            return data

        items = body.get("items")
        if isinstance(items, list):
            return items

        return []

    def _data(self, path: str, ttl: int) -> list[dict]:
        body = self._get(path, ttl)
        return self._items(body)

    # ------------------------------------------------------------------
    # EVENTS / FIXTURES
    # ------------------------------------------------------------------

    def fixtures_date(self, d: date) -> list[dict]:
        """Return football events scheduled for one UTC date."""

        day = d.isoformat()

        return self._data(
            f"events/?date_from={day}&date_to={day}&limit=200",
            ttl=3 * 3600,
        )

    def fixtures_live(self) -> list[dict]:
        """Return currently live football events."""

        return self._data(
            "events/live/?limit=200",
            ttl=30,
        )

    # ------------------------------------------------------------------
    # RESULTS
    # ------------------------------------------------------------------

    def results_date(self, d: date) -> list[dict]:
        """Return finished events for one UTC date."""

        day = d.isoformat()

        return self._data(
            f"events/?date_from={day}&date_to={day}"
            "&status=finished&limit=200",
            ttl=4 * 3600,
        )

    def results_yesterday(self) -> list[dict]:
        """Return yesterday's finished football events."""

        yesterday = date.today() - timedelta(days=1)

        return self.results_date(yesterday)

    # ------------------------------------------------------------------
    # MATCH DETAIL / SUB-RESOURCES
    # ------------------------------------------------------------------

    def fixture(self, fixture_id: str) -> dict:
        """Return one event's complete static detail."""

        body = self._get(
            f"events/{fixture_id}/",
            ttl=5 * 60,
        )

        if isinstance(body, dict):
            return body

        return {}

    def fixture_odds(self, fixture_id: str) -> list[dict]:
        """Return free consensus odds for one event."""

        body = self._get(
            f"events/{fixture_id}/odds/",
            ttl=2 * 60,
        )

        if isinstance(body, list):
            return body

        if isinstance(body, dict):
            results = body.get("results")
            if isinstance(results, list):
                return results

            data = body.get("data")
            if isinstance(data, list):
                return data

            items = body.get("items")
            if isinstance(items, list):
                return items

        return []

    def fixture_lineups(self, fixture_id: str) -> Any:
        """Return confirmed/predicted lineup information."""

        return self._get(
            f"events/{fixture_id}/lineups/",
            ttl=3 * 3600,
        )

    def fixture_stats(self, fixture_id: str) -> Any:
        """Return match statistics and xG/shot data when available."""

        return self._get(
            f"events/{fixture_id}/stats/",
            ttl=120,
        )

    def fixture_events(self, fixture_id: str) -> Any:
        """Return incidents: goals, cards, substitutions, VAR, etc."""

        return self._get(
            f"events/{fixture_id}/incidents/",
            ttl=60,
        )

    def fixture_h2h(self, fixture_id: str) -> Any:
        """Return head-to-head information for an event."""

        return self._get(
            f"events/{fixture_id}/h2h/",
            ttl=6 * 3600,
        )

    # ------------------------------------------------------------------
    # CAPTURE
    # ------------------------------------------------------------------

    def capture_bulletin(self) -> dict:
        """Capture today's/tomorrow's fixtures, yesterday's results,
        and one live snapshot.

        No prediction endpoint is called.
        """

        today = date.today()
        tomorrow = today + timedelta(days=1)

        fixtures = (
            self.fixtures_date(today)
            + self.fixtures_date(tomorrow)
        )

        results = self.results_yesterday()

        live = self.fixtures_live()

        return {
            "fixtures": fixtures,
            "results": results,
            "live": live,
            "api_calls_today": budget_today("goaldir"),
        }

    # ------------------------------------------------------------------
    # PRE-MATCH ENRICHMENT
    # ------------------------------------------------------------------

    def enrich_imminent(
        self,
        fixtures: list[dict],
        now_iso_kickoff_key: str = "kickoffUtc",
    ) -> list[dict]:
        """Enrich imminent fixtures with odds and lineups.

        This method does NOT request Goaldir predictions.
        """

        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)

        scored: list[tuple[float, dict]] = []

        for fx in fixtures:
            raw = (
                fx.get(now_iso_kickoff_key)
                or fx.get("kickoff")
                or fx.get("event_date")
                or fx.get("date")
                or ""
            )

            try:
                kickoff = datetime.fromisoformat(
                    str(raw).replace("Z", "+00:00")
                )
            except Exception:
                continue

            if kickoff.tzinfo is None:
                kickoff = kickoff.replace(tzinfo=timezone.utc)

            hours = (
                kickoff - now
            ).total_seconds() / 3600

            if -0.25 <= hours <= LINEUP_HORIZON_HOURS:
                scored.append((hours, fx))

        scored.sort(key=lambda item: item[0])

        out: list[dict] = []

        for _, fx in scored[:LINEUP_MAX_PER_RUN]:
            fixture_id = str(
                fx.get("id")
                or fx.get("event_id")
                or ""
            )

            if not fixture_id:
                continue

            try:
                if not fx.get("odds"):
                    fx["odds"] = self.fixture_odds(fixture_id)
            except Exception:
                pass

            try:
                if not fx.get("lineups"):
                    fx["lineups"] = self.fixture_lineups(
                        fixture_id
                    )
            except Exception:
                pass

            out.append(fx)

        return out
