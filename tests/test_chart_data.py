"""Multi-timeframe chart payload and per-month CPR history."""

import numpy as np
import pandas as pd
import pytest

import run as runmod
from indicators import cpr_history, ema, supertrend, swing_cpr


def _df(days=120, start="2026-04-01"):
    idx = pd.date_range(start, periods=days, freq="D")
    rng = np.random.default_rng(7)
    close = 100 + np.cumsum(rng.normal(0, 1, days))
    return pd.DataFrame({
        "open": close - 0.2, "high": close + 1.0, "low": close - 1.0,
        "close": close, "volume": np.full(days, 1000.0),
    }, index=idx)


def test_cpr_history_matches_swing_cpr_for_current_month():
    df = _df()
    segs = cpr_history(df)
    cpr = swing_cpr(df)
    last = segs[-1]
    assert last["pivot"] == cpr.pivot
    assert last["r1"] == cpr.r1
    assert last["s1"] == cpr.s1
    # one segment per month that has a completed prior month
    assert len(segs) == 3  # May, Jun, Jul for an Apr-Jul frame


def test_build_chart_data_shape(monkeypatch):
    df = _df()
    st = supertrend(df)

    def fake_fetch(symbol, asset_class, limit, timeframe="1d"):
        return df

    monkeypatch.setattr(runmod.prices, "fetch", fake_fetch)
    data = runmod.build_chart_data("BTC/USDT", "crypto", df, st, 500)

    assert set(data) == {"1d", "4h", "1w", "cpr"}
    bar = data["1d"]["candles"][0]
    assert set(bar) == {"time", "open", "high", "low", "close"}
    assert isinstance(bar["time"], int)
    stp = data["1d"]["st"][0]
    assert stp["dir"] in ("bull", "bear")
    seg = data["cpr"][0]
    assert seg["start"] < seg["end"]
    assert all(k in seg for k in ("pivot", "bc", "tc", "r1", "s1"))


def test_build_chart_data_degrades_when_tf_unavailable(monkeypatch):
    df = _df()
    st = supertrend(df)

    def fake_fetch(symbol, asset_class, limit, timeframe="1d"):
        raise RuntimeError("venue has no 4h bars")

    monkeypatch.setattr(runmod.prices, "fetch", fake_fetch)
    data = runmod.build_chart_data("X", "crypto", df, st, 500)
    assert "1d" in data and "cpr" in data
    assert "4h" not in data and "1w" not in data


# --- 50/200 EMA ---------------------------------------------------------------

def test_ema_seeds_with_sma_like_pine():
    s = pd.Series(np.arange(1, 11, dtype=float))
    out = ema(s, 3)
    assert out.iloc[:2].isna().all()
    assert out.iloc[2] == pytest.approx(2.0)          # SMA of 1,2,3
    assert out.iloc[3] == pytest.approx(0.5 * 4 + 0.5 * 2.0)


def test_ema_all_nan_when_history_is_shorter_than_the_period():
    assert ema(pd.Series([1.0, 2.0]), 200).isna().all()


def test_chart_payload_carries_both_emas():
    df = _df(days=260)
    data = runmod._tf_series(df, supertrend(df))
    assert len(data["ema50"]) == 260 - 49
    assert len(data["ema200"]) == 260 - 199
    assert set(data["ema50"][0]) == {"time", "value"}


def test_ema200_omitted_for_short_history():
    df = _df(days=120)
    data = runmod._tf_series(df, supertrend(df))
    assert data["ema50"] and data["ema200"] == []
