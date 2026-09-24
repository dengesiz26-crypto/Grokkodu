from __future__ import annotations
import json
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from xgboost import XGBClassifier
import joblib
from .config import PROCESSED, MODELS
from .features import add_targets, infer_columns


def train():
    path = PROCESSED / "historical_matches.parquet"
    if not path.exists():
        raise RuntimeError("Run ingest first")
    df = add_targets(pd.read_parquet(path)).dropna(subset=["result", "ou25", "btts"])
    feats = [c for c in infer_columns(df) if c not in ("home_goals", "away_goals")]
    if len(feats) < 3:
        # ratings-only fallback: skip XGB if we don't have rich columns
        (MODELS / "feature_columns.json").write_text(json.dumps({"skipped": True, "reason": "thin features"}))
        return str(MODELS / "feature_columns.json")
    X = df[feats]
    models = {}
    for target, params in (
        ("result", dict(objective="multi:softprob", num_class=3, eval_metric="mlogloss", n_estimators=400, max_depth=4, learning_rate=0.04, subsample=0.85, colsample_bytree=0.85, random_state=42)),
        ("ou25", dict(objective="binary:logistic", eval_metric="logloss", n_estimators=350, max_depth=4, learning_rate=0.04, subsample=0.85, colsample_bytree=0.85, random_state=42)),
        ("btts", dict(objective="binary:logistic", eval_metric="logloss", n_estimators=350, max_depth=4, learning_rate=0.04, subsample=0.85, colsample_bytree=0.85, random_state=42)),
    ):
        pipe = Pipeline([("imputer", SimpleImputer(strategy="median")), ("model", XGBClassifier(**params))])
        pipe.fit(X, df[target].astype(int))
        models[target] = pipe
    out = MODELS / "ensemble.joblib"
    joblib.dump({"models": models, "features": feats}, out)
    (MODELS / "feature_columns.json").write_text(json.dumps(feats, indent=2))
    return str(out)
