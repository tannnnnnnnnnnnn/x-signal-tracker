"""Multi-timeframe chart payload and per-month CPR history."""

import numpy as np
import pandas as pd

import run as runmod
from indicators import cpr_history, supertrend, swing_cpr


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
