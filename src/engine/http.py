"""Shared HTTP cache. Goaldir requests always fetch fresh data."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import requests

from .db import connect, init


SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "KALE-Engine/2.0",
    "Accept": "application/json",
})


def _key(url: str, params: dict | None) -> str:
    blob = url + "?" + json.dumps(params or {}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def cached_get(
    url: str,
    *,
    headers=None,
    params=None,
    ttl=3600,
    timeout=30,
    provider="http",
):
    init()

    k = _key(url, params)
    c = connect()

    # Goaldir must always fetch fresh data.
    # Other providers continue using the TTL cache.
    use_cache = provider.lower() != "goaldir"

    if use_cache:
        row = c.execute(
            """
            SELECT fetched_at, ttl_seconds, body, status
            FROM http_cache
            WHERE cache_key=?
            """,
            (k,),
        ).fetchone()

        if row:
            try:
                fetched = datetime.fromisoformat(row["fetched_at"])
                age = (
                    datetime.now(timezone.utc) - fetched
                ).total_seconds()

                if (
                    age < (row["ttl_seconds"] or ttl)
                    and row["status"] == 200
                ):
                    c.close()
                    return json.loads(row["body"])

            except Exception:
                pass

    # No application-side daily request limit.
    r = SESSION.get(
        url,
        headers=headers or {},
        params=params or {},
        timeout=timeout,
    )

    c.execute(
        """
        INSERT INTO api_log(
            ts,
            provider,
            path,
            status,
            bytes
        )
        VALUES(datetime('now'),?,?,?,?)
        """,
        (
            provider,
            url,
            r.status_code,
            len(r.content),
        ),
    )

    body_text = r.text

    # Store the response, but Goaldir will not read it
    # as a cached response on the next request.
    c.execute(
        """
        INSERT INTO http_cache(
            cache_key,
            fetched_at,
            ttl_seconds,
            body,
            status
        )
        VALUES(?,?,?,?,?)
        ON CONFLICT(cache_key) DO UPDATE SET
            fetched_at=excluded.fetched_at,
            ttl_seconds=excluded.ttl_seconds,
            body=excluded.body,
            status=excluded.status
        """,
        (
            k,
            datetime.now(timezone.utc).isoformat(),
            ttl,
            body_text,
            r.status_code,
        ),
    )

    c.commit()
    c.close()

    r.raise_for_status()

    try:
        return r.json()
    except Exception:
        return {"raw": body_text}


def budget_today(provider="goaldir") -> int:
    """
    Return the number of API requests made today.

    This is reporting only.
    It does not limit API requests.
    """
    init()

    c = connect()

    n = c.execute(
        """
        SELECT COUNT(*)
        FROM api_log
        WHERE provider=?
          AND ts >= datetime('now','start of day')
        """,
        (provider,),
    ).fetchone()[0]

    c.close()

    return int(n)
