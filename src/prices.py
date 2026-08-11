"""OHLCV fetching. Crypto via CCXT/Binance, everything else via yfinance (spec §5)."""

from __future__ import annotations

import ccxt
import pandas as pd

MIN_BARS = 500  # spec §6 step 3


class PriceFetchError(RuntimeError):
    pass


def _frame(rows: list[list], tz: str | None = None, normalize: bool = True) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    if tz:
        df["date"] = df["date"].dt.tz_convert(tz)
    idx = df["date"].dt.tz_localize(None)
    if normalize:
        idx = idx.dt.normalize()
    return df.set_index(idx).drop(columns=["ts", "date"])


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


def fetch_crypto(symbol: str, limit: int = MIN_BARS, timeframe: str = "1d") -> pd.DataFrame:
    """Bars for a CCXT pair, e.g. 'BTC/USDT', trying each venue in turn."""
    errors = []
    for name in CRYPTO_EXCHANGES:
        try:
            ex = _exchange(name)
            if symbol not in _markets_cache[name]:
                errors.append(f"{name}: not listed")
                continue
            rows = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            if rows:
                return _frame(rows, normalize=timeframe in ("1d", "1w"))
            errors.append(f"{name}: no bars")
        except Exception as exc:  # ccxt raises a wide family
            errors.append(f"{name}: {exc}")
    raise PriceFetchError(f"{symbol} unavailable — " + "; ".join(errors))


# yfinance has no 4h interval; fetch 1h (capped at ~730d) and resample.
_YF_INTERVAL = {"1d": "1d", "1w": "1wk", "4h": "1h"}


def fetch_yfinance(symbol: str, limit: int = MIN_BARS, timeframe: str = "1d") -> pd.DataFrame:
    """Bars for equities, ETFs, commodities, FX and NSE tickers."""
    import yfinance as yf

    if timeframe == "4h":
        period = "180d"  # yfinance caps 1h data; 180d ≈ 700 4h bars for equities
    elif timeframe == "1w":
        period = f"{int(limit * 7.2) + 40}d"
    else:
        period = f"{int(limit * 1.6) + 40}d"  # weekends and holidays thin the series
    try:
        raw = yf.Ticker(symbol).history(
            period=period, interval=_YF_INTERVAL[timeframe], auto_adjust=False
        )
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
    df.index = pd.to_datetime(df.index).tz_localize(None)
    if timeframe == "4h":
        df = (
            df.resample("4h")
            .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
            .dropna(subset=["close"])
        )
    else:
        df.index = df.index.normalize()
    return df


def fetch(symbol: str, asset_class: str, limit: int = MIN_BARS, timeframe: str = "1d") -> pd.DataFrame:
    if asset_class == "onchain":
        import onchain

        return onchain.fetch_ohlcv(symbol, timeframe)
    if asset_class == "crypto":
        return fetch_crypto(symbol, limit, timeframe)
    return fetch_yfinance(symbol, limit, timeframe)
