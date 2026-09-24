from src.engine.value import devig, value, decide
from src.engine.models.poisson import markets


def test_devig():
    p = devig([2, 3])
    assert abs(sum(p) - 1) < 1e-9


def test_value():
    v = value(0.6, 2)
    assert round(v["ev"], 2) == 0.2


def test_decide_filters_longshots():
    assert decide(0.22, 6.0) == "ABSTAIN"
    assert decide(0.58, 2.05) in {"CANDIDATE", "STRONG", "WATCH"}


def test_poisson_sums():
    m = markets(1.4, 1.1)
    s = m["home"] + m["draw"] + m["away"]
    assert abs(s - 1) < 1e-6
    assert m["over25"] + m["under25"] == 1 or abs(m["over25"] + m["under25"] - 1) < 1e-6
