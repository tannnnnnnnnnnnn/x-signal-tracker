"""Spec §11. The two golden fixtures sit on opposite sides of the CPR inversion
branch, which is the whole reason both exist."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from indicators import (
    CPR,
    cpr_width_history,
    is_narrow_cpr,
    supertrend,
    swing_cpr,
    true_range,
    wilder_atr,
)
from verdict import cpr_position, judge, sentiment_disagrees

# --- CPR identities, spec §7.2 -------------------------------------------------


def make_cpr(h: float, low: float, c: float) -> CPR:
    pivot = (h + low + c) / 3
    bc = (h + low) / 2
    tc = 2 * pivot - bc
    return CPR(
        pivot, bc, tc, 2 * pivot - low, 2 * pivot - h,
        h, low, c, abs(tc - bc) / pivot, tc < bc, "test",
    )


# Prior-month OHLC behind each fixture. GOLD's is back-solved from the plotted
# R1/S1; BTC's is measured directly off Binance.
GOLD_JUL = (5419.319, 4098.741, 4671.793)
BTC_JUL = (66956.15, 57800.19, 62887.88)


@pytest.mark.parametrize(
    "h,low,c",
    [GOLD_JUL, BTC_JUL, (100.0, 50.0, 75.0)],
    ids=["gold", "btc", "degenerate-close-at-midpoint"],
)
def test_cpr_identities(h, low, c):
    cpr = make_cpr(h, low, c)
    assert cpr.tc - cpr.pivot == pytest.approx(cpr.pivot - cpr.bc, abs=1e-9)
    assert (cpr.prior_high + cpr.prior_low) / 2 == pytest.approx(cpr.bc, abs=1e-9)
    assert cpr.r1 == pytest.approx(2 * cpr.pivot - cpr.prior_low, abs=1e-9)
    assert cpr.s1 == pytest.approx(2 * cpr.pivot - cpr.prior_high, abs=1e-9)


@pytest.mark.parametrize("h,low,c", [GOLD_JUL, BTC_JUL], ids=["gold", "btc"])
def test_r1_s1_midpoint_identity_is_vacuous(h, low, c):
    """(r1+s1)/2 == tc holds for EVERY CPR, by algebra.

    Regression guard on a real analysis error: this identity was once used to
    argue that lines 4 and 5 were the prior high/low. It confirms unconditionally
    and therefore proves nothing about line identity.
    """
    cpr = make_cpr(h, low, c)
    assert (cpr.r1 + cpr.s1) / 2 == pytest.approx(cpr.tc, rel=1e-12)
    # ...and the prior high/low are demonstrably NOT r1/s1:
    assert cpr.r1 != pytest.approx(cpr.prior_high, rel=1e-6)
    assert cpr.s1 != pytest.approx(cpr.prior_low, rel=1e-6)


def test_cpr_inversion_detected():
    assert make_cpr(*GOLD_JUL).inverted is True     # gold IS inverted
    assert make_cpr(*BTC_JUL).inverted is False     # BTC is not


def test_band_edges_survive_inversion():
    inv = make_cpr(*GOLD_JUL)
    assert inv.top == pytest.approx(inv.bc)      # inverted: bc is the top
    assert inv.bottom == pytest.approx(inv.tc)
    norm = make_cpr(*BTC_JUL)
    assert norm.top == pytest.approx(norm.tc)    # normal: tc is the top
    assert norm.bottom == pytest.approx(norm.bc)


# --- Golden fixture: BTCUSDT, inverted, spec §11 -------------------------------

# Plotted values, read off the chart in SwingCPR's order: pivot, BC, TC, R1, S1.
BTC = dict(
    pivot=62548.07, bc=62378.17, tc=62717.98, r1=67295.96, s1=58140.00,
    close=64622.00, supertrend=60426.28,
)


def test_btc_golden_cpr():
    """Every plotted line reproduces from Binance's July 2026 bars."""
    cpr = make_cpr(*BTC_JUL)
    assert cpr.pivot == pytest.approx(BTC["pivot"], abs=0.01)
    assert cpr.bc == pytest.approx(BTC["bc"], abs=0.01)
    assert cpr.tc == pytest.approx(BTC["tc"], abs=0.01)
    assert cpr.r1 == pytest.approx(BTC["r1"], abs=0.01)
    assert cpr.s1 == pytest.approx(BTC["s1"], abs=0.01)
    assert cpr.inverted is False
    assert cpr.width == pytest.approx(0.005433, rel=1e-3)


def test_btc_golden_verdict():
    cpr = make_cpr(*BTC_JUL)
    assert cpr_position(BTC["close"], cpr) == "above"

    class FakeST:
        direction = "bull"

    v = judge(BTC["close"], FakeST(), cpr, width_history=[])
    assert v.verdict == "Strong bullish"
    assert v.inverted_cpr is False
    assert v.conflict is False


# --- Golden fixture: gold, non-inverted, spec §11 ------------------------------

GOLD = dict(
    pivot=4729.951, bc=4759.031, tc=4700.872, r1=5361.161, s1=4040.583,
    close=4596.440, supertrend=4849.832,
)


def test_gold_golden_cpr():
    cpr = make_cpr(*GOLD_JUL)
    assert cpr.pivot == pytest.approx(GOLD["pivot"], abs=0.01)
    assert cpr.bc == pytest.approx(GOLD["bc"], abs=0.01)
    assert cpr.tc == pytest.approx(GOLD["tc"], abs=0.01)
    assert cpr.r1 == pytest.approx(GOLD["r1"], abs=0.01)
    assert cpr.s1 == pytest.approx(GOLD["s1"], abs=0.01)
    assert cpr.inverted is True
    assert cpr.width == pytest.approx(0.012296, rel=1e-3)


def test_gold_golden_verdict():
    """The inverted case: close sits below TC, which is the LOWER edge here."""
    cpr = make_cpr(*GOLD_JUL)
    assert cpr.bottom == pytest.approx(cpr.tc)
    assert cpr_position(GOLD["close"], cpr) == "below"

    class FakeST:
        direction = "bear"

    v = judge(GOLD["close"], FakeST(), cpr, width_history=[])
    assert v.verdict == "Strong bearish"
    assert v.inverted_cpr is True


# --- Verdict grid: 6 cells x 2 orientations, spec §11 --------------------------

NORMAL = make_cpr(120.0, 80.0, 110.0)     # tc > bc
INVERTED = make_cpr(120.0, 80.0, 90.0)    # tc < bc


@pytest.mark.parametrize("cpr", [NORMAL, INVERTED], ids=["normal", "inverted"])
@pytest.mark.parametrize(
    "direction,offset,expected",
    [
        ("bull", +10.0, "Strong bullish"),
        ("bull", 0.0, "Bullish, indecisive"),
        ("bull", -10.0, "Conflict"),
        ("bear", +10.0, "Conflict"),
        ("bear", 0.0, "Bearish, indecisive"),
        ("bear", -10.0, "Strong bearish"),
    ],
)
def test_verdict_grid_both_orientations(cpr, direction, offset, expected):
    if offset > 0:
        close = cpr.top + offset
    elif offset < 0:
        close = cpr.bottom + offset
    else:
        close = (cpr.top + cpr.bottom) / 2

    class FakeST:
        pass

    FakeST.direction = direction
    assert judge(close, FakeST(), cpr, []).verdict == expected


@pytest.mark.parametrize("cpr", [NORMAL, INVERTED], ids=["normal", "inverted"])
def test_verdict_boundaries_are_inside(cpr):
    assert cpr_position(cpr.top, cpr) == "inside"
    assert cpr_position(cpr.bottom, cpr) == "inside"


# --- Supertrend ----------------------------------------------------------------


def synthetic(n: int = 400, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1.5, n))
    high = close + rng.uniform(0.2, 2.0, n)
    low = close - rng.uniform(0.2, 2.0, n)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close}, index=idx)


def test_wilder_atr_matches_pine_rma():
    """Pine ta.rma: seed = SMA of the first `period` TRs, then recurse."""
    df = synthetic(60)
    atr = wilder_atr(df["high"], df["low"], df["close"], 22)
    tr = true_range(df["high"], df["low"], df["close"])

    manual = tr.iloc[:22].mean()
    for i in range(22, len(df)):
        manual = (manual * 21 + tr.iloc[i]) / 22
    assert atr.iloc[-1] == pytest.approx(manual, rel=1e-12)


def test_wilder_atr_is_not_plain_ewm():
    """Guards the §7.1 warning: the naive ewm shortcut gives a different answer."""
    df = synthetic(60)
    ours = wilder_atr(df["high"], df["low"], df["close"], 22).iloc[-1]
    naive = true_range(df["high"], df["low"], df["close"]).ewm(alpha=1 / 22, adjust=False).mean().iloc[-1]
    assert ours != pytest.approx(naive, rel=1e-9)


def test_atr_warmup_is_nan():
    df = synthetic(60)
    atr = wilder_atr(df["high"], df["low"], df["close"], 22)
    assert atr.iloc[:21].isna().all()
    assert not np.isnan(atr.iloc[21])


def test_supertrend_line_never_straddles_price_wrongly():
    df = synthetic()
    st = supertrend(df)
    s = st.series.dropna()
    closes = df.loc[s.index, "close"]
    bull, bear = s["direction"] == "bull", s["direction"] == "bear"
    assert (s.loc[bull, "supertrend"] <= closes[bull]).all()
    assert (s.loc[bear, "supertrend"] >= closes[bear]).all()


def test_supertrend_flips_on_a_reversal():
    df = synthetic()
    dirs = supertrend(df).series["direction"].dropna()
    assert set(dirs.unique()) == {"bull", "bear"}, "fixture should contain both regimes"


def test_supertrend_rejects_short_history():
    with pytest.raises(ValueError, match="not enough bars"):
        supertrend(synthetic(10))


# --- Monthly stepping, spec §11 ------------------------------------------------


def test_cpr_constant_within_month_and_steps_on_the_first():
    df = synthetic(400)
    mid_july = swing_cpr(df, asof=pd.Timestamp("2024-07-15"))
    end_july = swing_cpr(df, asof=pd.Timestamp("2024-07-31"))
    aug = swing_cpr(df, asof=pd.Timestamp("2024-08-01"))

    assert mid_july.pivot == end_july.pivot
    assert mid_july.period_label == "2024-06"
    assert aug.period_label == "2024-07"
    assert aug.pivot != end_july.pivot


def test_cpr_rejects_insufficient_history():
    df = synthetic(10)
    with pytest.raises(ValueError):
        swing_cpr(df)


def test_narrow_cpr_flag():
    assert is_narrow_cpr(0.01, [0.02, 0.03]) is True
    assert is_narrow_cpr(0.05, [0.02, 0.03]) is False
    assert is_narrow_cpr(0.01, []) is False


def test_width_history_excludes_in_progress_month():
    df = synthetic(400)
    hist = cpr_width_history(df, lookback=6)
    assert len(hist) == 6
    assert all(w > 0 for w in hist)


# --- Sentiment disagreement ----------------------------------------------------


def test_sentiment_disagreement():
    cpr = NORMAL

    class Bear:
        direction = "bear"

    v = judge(cpr.bottom - 5, Bear(), cpr, [])
    assert v.verdict == "Strong bearish"
    assert sentiment_disagrees("bullish", v) is True
    assert sentiment_disagrees("bearish", v) is False
    assert sentiment_disagrees("neutral", v) is False
    assert sentiment_disagrees(None, v) is False
