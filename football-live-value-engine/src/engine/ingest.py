from __future__ import annotations
from .providers.football_data import download_history
from .config import PROCESSED


def ingest():
    df = download_history()
    dest = PROCESSED / "historical_matches.parquet"
    df.to_parquet(dest, index=False)
    summary = {
        "rows": int(len(df)),
        "leagues": int(df["league"].nunique()),
        "from": str(df["date"].min().date()),
        "to": str(df["date"].max().date()),
        "path": str(dest),
    }
    return summary
