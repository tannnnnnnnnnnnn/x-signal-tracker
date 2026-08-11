"""On-chain (DEX) tokens — pump.fun and friends.

A trusted account posting a raw Solana contract address is a signal about that
token, not about SOL. Resolution: DexScreener maps the CA to its symbol, name
and deepest pool; GeckoTerminal serves the pool's OHLCV. Both APIs are free and
keyless.

Symbols for this asset class are stored as ``solana:<contract-address>`` so
they survive round-trips through the DB and outcomes refetching.
"""

from __future__ import annotations

import json
import re
import urllib.request

import pandas as pd

DEXSCREENER = "https://api.dexscreener.com/latest/dex/tokens/{ca}"
GECKOTERMINAL = (
    "https://api.geckoterminal.com/api/v2/networks/{network}/pools/{pool}"
    "/ohlcv/{tf}?aggregate={agg}&limit=1000"
)

# Base58, Solana address length. Requiring both a digit and letters of both
# cases keeps ordinary words and hashes of other alphabets from matching.
SOLANA_CA = re.compile(r"\b(?=\w*\d)(?=\w*[a-z])(?=\w*[A-Z])[1-9A-HJ-NP-Za-km-z]{32,44}\b")

PREFIX = "solana:"


class OnchainError(RuntimeError):
    pass


def find_contracts(text: str) -> list[str]:
    return SOLANA_CA.findall(text or "")


def is_onchain_symbol(token: str) -> bool:
    return token.lower().startswith(PREFIX) or bool(SOLANA_CA.fullmatch(token.strip()))


def to_symbol(token: str) -> str:
    """Normalise a raw CA or 'solana:<ca>' token to the stored symbol form."""
    ca = token.strip()
    if ca.lower().startswith(PREFIX):
        ca = ca[len(PREFIX):]
    return PREFIX + ca


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "x-signal-tracker"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


_meta_cache: dict[str, dict] = {}


def resolve(symbol: str) -> dict:
    """CA -> {symbol, name, pool, dex} via DexScreener, deepest pool first."""
    ca = symbol[len(PREFIX):] if symbol.lower().startswith(PREFIX) else symbol
    if ca in _meta_cache:
        return _meta_cache[ca]

    data = _get(DEXSCREENER.format(ca=ca))
    pairs = [p for p in (data.get("pairs") or []) if p.get("chainId") == "solana"]
    if not pairs:
        raise OnchainError(f"DexScreener has no Solana pool for {ca}")
    best = max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd", 0))

    meta = {
        "symbol": best["baseToken"]["symbol"],
        "name": best["baseToken"].get("name") or best["baseToken"]["symbol"],
        "pool": best["pairAddress"],
        "dex": best.get("dexId", "?"),
        "ca": ca,
    }
    _meta_cache[ca] = meta
    return meta


# GeckoTerminal timeframe endpoints. Weekly is resampled from daily — GT has no
# native week candles.
_TF = {"4h": ("hour", 4), "1d": ("day", 1)}


def fetch_ohlcv(symbol: str, timeframe: str = "1d") -> pd.DataFrame:
    meta = resolve(symbol)
    tf, agg = _TF["1d" if timeframe == "1w" else timeframe]
    data = _get(GECKOTERMINAL.format(network="solana", pool=meta["pool"], tf=tf, agg=agg))
    rows = data["data"]["attributes"]["ohlcv_list"]
    if not rows:
        raise OnchainError(f"GeckoTerminal returned no {timeframe} bars for {meta['symbol']}")

    rows = sorted(rows)  # API returns newest first
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df.index = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_localize(None)
    df = df.drop(columns=["ts"]).dropna(subset=["close"])
    if timeframe == "1d":
        df.index = df.index.normalize()
    elif timeframe == "1w":
        df = (
            df.resample("W-MON", label="left", closed="left")
            .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
            .dropna(subset=["close"])
        )
    if df.empty:
        raise OnchainError(f"no usable {timeframe} bars for {meta['symbol']}")
    return df
