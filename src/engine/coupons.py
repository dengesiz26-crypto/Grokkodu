from math import prod


def singles(candidates):
    return sorted(candidates, key=lambda x: x.get("ev") or -999, reverse=True)


def accumulator(candidates, max_legs=None):
    pool = [c for c in candidates if c.get("decision") == "CANDIDATE" or c.get("decision") == "STRONG"]
    pool = sorted(pool, key=lambda x: (x.get("ev") or -999, x.get("probability") or 0), reverse=True)
    if max_legs is not None:
        pool = pool[:max_legs]
    if not pool:
        return None
    seen, legs = set(), []
    for c in pool:
        k = c.get("match_key") or f"{c.get('home')}|{c.get('away')}"
        if k in seen:
            continue
        legs.append(c)
        seen.add(k)
    if not legs:
        return None
    return {
        "legs": legs,
        "combined_odds": prod(x.get("market_odds") or x.get("odds") or 1 for x in legs),
        "combined_probability": prod(x.get("probability") or 0 for x in legs),
    }
