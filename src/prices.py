"""OHLCV fetching. Crypto via CCXT/Binance, everything else via yfinance (spec §5)."""

from __future__ import annotations

import ccxt
import pandas as pd

MIN_BARS = 500  # spec §6 step 3


class PriceFetchError(RuntimeError):
    pass


def _frame(rows: list[list], tz: str | None = None) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    if tz:
        df["date"] = df["date"].dt.tz_convert(tz)
    return df.set_index(df["date"].dt.tz_localize(None).dt.normalize()).drop(columns=["ts", "date"])


# Binance first for depth and history, then venues that list newer tokens.
# HYPE is the live example: Binance carries only the perpetual, Bybit has spot.
CRYPTO_EXCHANGES = ("binance", "bybit", "okx")
_markets_cache: dict[str, set] = {}


def _exchange(name: str):
    ex = getattr(ccxt, name)({"enableRateLimit": True})
    if name not in _markets_cache:
        ex.load_markets()
        _markets_cache[name] = set(ex.symbols)
    return ex


def fetch_crypto(symbol: str, limit: int = MIN_BARS) -> pd.DataFrame:
    """Daily bars for a CCXT pair, e.g. 'BTC/USDT', trying each venue in turn."""
    errors = []
    for name in CRYPTO_EXCHANGES:
        try:
            ex = _exchange(name)
            if symbol not in _markets_cache[name]:
                errors.append(f"{name}: not listed")
                continue
            rows = ex.fetch_ohlcv(symbol, timeframe="1d", limit=limit)
            if rows:
                return _frame(rows)
            errors.append(f"{name}: no bars")
        except Exception as exc:  # ccxt raises a wide family
            errors.append(f"{name}: {exc}")
    raise PriceFetchError(f"{symbol} unavailable — " + "; ".join(errors))


def fetch_yfinance(symbol: str, limit: int = MIN_BARS) -> pd.DataFrame:
    """Daily bars for equities, ETFs, commodities, FX and NSE tickers."""
    import yfinance as yf

    period_days = int(limit * 1.6) + 40  # weekends and holidays thin the series
    try:
        raw = yf.Ticker(symbol).history(period=f"{period_days}d", interval="1d", auto_adjust=False)
    except Exception as exc:
        raise PriceFetchError(f"yfinance {symbol}: {exc}") from exc
    if raw.empty:
        raise PriceFetchError(f"yfinance {symbol}: no bars returned")

    df = raw.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
    # yfinance can emit a trailing placeholder bar with NaN close (pre-open, or
    # a settling session); a NaN close reaches SQLite as NULL and kills the run.
    df = df.dropna(subset=["close"])
    if df.empty:
        raise PriceFetchError(f"yfinance {symbol}: all bars have NaN close")
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    return df


def fetch(symbol: str, asset_class: str, limit: int = MIN_BARS) -> pd.DataFrame:
    if asset_class == "crypto":
        return fetch_crypto(symbol, limit)
    return fetch_yfinance(symbol, limit)
