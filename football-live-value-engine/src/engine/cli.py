from __future__ import annotations
import argparse, json
from .db import init


def main():
    ap = argparse.ArgumentParser(prog="kale")
    ap.add_argument(
        "command",
        choices=["init", "ingest", "train", "backtest", "capture", "pre_match", "live", "settle", "paper_daemon"],
    )
    a = ap.parse_args()
    init()
    if a.command == "init":
        print("initialized")
        return
    if a.command == "ingest":
        from .ingest import ingest
        print(json.dumps(ingest(), indent=2, default=str))
        return
    if a.command == "train":
        from .train import train
        print(train())
        return
    if a.command == "backtest":
        import pandas as pd
        from .config import PROCESSED, REPORTS
        from .backtest import walk_forward
        df = pd.read_parquet(PROCESSED / "historical_matches.parquet")
        r = walk_forward(df)
        REPORTS.mkdir(parents=True, exist_ok=True)
        (REPORTS / "walk_forward.json").write_text(json.dumps(r, indent=2))
        print(json.dumps(r, indent=2))
        return
    if a.command in {"capture", "pre_match"}:
        from .capture import capture
        print(json.dumps(capture(), indent=2, default=str))
        return
    if a.command == "live":
        from .live import scan_live
        print(json.dumps(scan_live(), indent=2, default=str))
        return
    if a.command == "settle":
        from .settle import settle
        print(json.dumps(settle(), indent=2, default=str))
        return
    if a.command == "paper_daemon":
        from .capture import capture
        from .settle import settle
        cap = capture()
        stl = settle()
        print(json.dumps({"capture": cap, "settle": stl}, indent=2, default=str))


if __name__ == "__main__":
    main()
