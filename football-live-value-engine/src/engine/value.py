from __future__ import annotations
from .config import MIN_EDGE, MIN_ODDS, MAX_ODDS, MIN_PROB


def implied(o):
    return 1 / o if o and o > 1 else None


def devig(prices):
    p = [implied(x) for x in prices]
    if any(x is None for x in p):
        return None
    s = sum(p)
    return [x / s for x in p]


def value(prob, odds):
    if prob is None or odds is None or odds <= 1:
        return None
    return {"probability": prob, "fair_odds": 1 / prob, "edge": prob - 1 / odds, "ev": prob * odds - 1}


def decide(prob: float, odds: float | None) -> str:
    if odds is None or odds <= 1.01:
        return "WATCH" if prob >= 0.62 else "ABSTAIN"
    if odds < MIN_ODDS or odds > MAX_ODDS or prob < MIN_PROB:
        return "ABSTAIN"
    edge = prob - 1 / odds
    ev = prob * odds - 1
    if edge >= 0.07 and ev >= 0.10 and prob >= 0.54:
        return "STRONG"
    if edge >= MIN_EDGE and ev >= 0.055:
        return "CANDIDATE"
    if edge >= 0.02:
        return "WATCH"
    return "ABSTAIN"
