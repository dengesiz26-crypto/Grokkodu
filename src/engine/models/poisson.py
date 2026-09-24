from __future__ import annotations
import math
import numpy as np

LN_FACT = [0.0]
for i in range(1, 17):
    LN_FACT.append(LN_FACT[-1] + math.log(i))


def poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam + k * math.log(lam) - LN_FACT[k])


def tau(h, a, lam, mu, rho):
    if h == 0 and a == 0:
        return 1 - lam * mu * rho
    if h == 0 and a == 1:
        return 1 + lam * rho
    if h == 1 and a == 0:
        return 1 + mu * rho
    if h == 1 and a == 1:
        return 1 - rho
    return 1


def score_matrix(lam: float, mu: float, rho: float = -0.08, max_goals: int = 8) -> np.ndarray:
    m = np.zeros((max_goals + 1, max_goals + 1))
    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            m[h, a] = max(0.0, tau(h, a, lam, mu, rho) * poisson_pmf(h, lam) * poisson_pmf(a, mu))
    s = m.sum()
    if s > 0:
        m /= s
    return m


def markets(lam: float, mu: float, rho: float = -0.08) -> dict:
    m = score_matrix(lam, mu, rho)
    home = float(np.tril(m, -1).sum())
    draw = float(np.trace(m))
    away = float(np.triu(m, 1).sum())
    over25 = float(sum(m[i, j] for i in range(m.shape[0]) for j in range(m.shape[1]) if i + j > 2))
    btts = float(m[1:, 1:].sum())
    idx = np.unravel_index(int(m.argmax()), m.shape)
    return {
        "home": home, "draw": draw, "away": away,
        "over25": over25, "under25": 1 - over25,
        "btts_yes": btts, "btts_no": 1 - btts,
        "most_likely": f"{idx[0]}-{idx[1]}",
        "lambda_home": lam, "lambda_away": mu,
    }


def live_markets(pre_h, pre_a, minute, hs, as_):
    played = min(90, max(1, minute))
    left = max(0.08, (90 - played) / 90)
    gap = hs - as_
    ch = 1.08 if gap < 0 else 0.94 if gap > 1 else 1.0
    ca = 1.08 if gap > 0 else 0.94 if gap < -1 else 1.0
    add = score_matrix(pre_h * left * ch, pre_a * left * ca, rho=0.0)
    # shift by current score
    H, A = add.shape
    full = np.zeros((H + hs, A + as_))
    full[hs:hs + H, as_:as_ + A] += add
    cut = full[: min(full.shape[0], 10), : min(full.shape[1], 10)]
    if cut.sum() > 0:
        cut = cut / cut.sum()
    home = float(sum(cut[i, j] for i in range(cut.shape[0]) for j in range(cut.shape[1]) if i > j))
    draw = float(sum(cut[i, i] for i in range(min(cut.shape))))
    away = float(sum(cut[i, j] for i in range(cut.shape[0]) for j in range(cut.shape[1]) if i < j))
    over25 = float(sum(cut[i, j] for i in range(cut.shape[0]) for j in range(cut.shape[1]) if i + j > 2))
    btts = float(sum(cut[i, j] for i in range(cut.shape[0]) for j in range(cut.shape[1]) if i > 0 and j > 0))
    return {
        "home": home, "draw": draw, "away": away,
        "over25": over25, "under25": 1 - over25,
        "btts_yes": btts, "btts_no": 1 - btts,
    }
