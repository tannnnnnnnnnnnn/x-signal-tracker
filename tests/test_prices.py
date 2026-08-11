"""Regression: yfinance trailing NaN-close bars must never reach the DB.

2026-08-11 07:00 run crashed with
`sqlite3.IntegrityError: NOT NULL constraint failed: snapshots.close`
because yfinance returned a placeholder bar whose Close was NaN.
"""

import sys
import types

import numpy as np
import pandas as pd
import pytest

from prices import PriceFetchError, fetch_yfinance


def _fake_yfinance(monkeypatch, raw: pd.DataFrame):
    mod = types.ModuleType("yfinance")

    class Ticker:
        def __init__(self, symbol):
            pass

        def history(self, **kwargs):
            return raw

    mod.Ticker = Ticker
    monkeypatch.setitem(sys.modules, "yfinance", mod)


def _raw(closes):
    idx = pd.date_range("2026-08-01", periods=len(closes), tz="America/New_York")
    return pd.DataFrame(
        {"Open": 1.0, "High": 2.0, "Low": 0.5, "Close": closes, "Volume": 100},
        index=idx,
    )


def test_trailing_nan_close_bar_is_dropped(monkeypatch):
    _fake_yfinance(monkeypatch, _raw([10.0, 11.0, np.nan]))
    df = fetch_yfinance("FAKE")
    assert len(df) == 2
    assert not df["close"].isna().any()
    assert float(df["close"].iloc[-1]) == 11.0


def test_all_nan_close_raises(monkeypatch):
    _fake_yfinance(monkeypatch, _raw([np.nan, np.nan]))
    with pytest.raises(PriceFetchError):
        fetch_yfinance("FAKE")
