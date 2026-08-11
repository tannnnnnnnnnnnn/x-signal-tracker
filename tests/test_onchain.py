"""On-chain (pump.fun) resolution and OHLCV, with mocked HTTP."""

import pandas as pd
import pytest

import onchain
from extract import Registry, extract_contracts

CA = "9cRCn9rGT8V2imeM2BaKs13yhMEais3ruM3rPvTGpump"

DEX_RESPONSE = {
    "pairs": [
        {"chainId": "solana", "dexId": "pumpswap", "pairAddress": "POOL1",
         "baseToken": {"symbol": "ANSEM", "name": "The Black Bull"},
         "liquidity": {"usd": 2_100_000}},
        {"chainId": "solana", "dexId": "raydium", "pairAddress": "POOL2",
         "baseToken": {"symbol": "ANSEM", "name": "The Black Bull"},
         "liquidity": {"usd": 40_000}},
        {"chainId": "bsc", "dexId": "pancake", "pairAddress": "POOL3",
         "baseToken": {"symbol": "FAKE", "name": "impostor"},
         "liquidity": {"usd": 9_900_000_000}},
    ]
}


@pytest.fixture(autouse=True)
def clear_cache():
    onchain._meta_cache.clear()


def test_find_contracts_matches_pump_ca():
    text = f"new runner. {CA} send it"
    assert onchain.find_contracts(text) == [CA]


def test_find_contracts_ignores_prose_and_tickers():
    assert onchain.find_contracts("gold and silver are over, buy $BTC now") == []
    assert onchain.find_contracts("BREAKINGNEWSTODAYBIGMOVESCOMINGSOON") == []


def test_resolve_picks_deepest_solana_pool(monkeypatch):
    monkeypatch.setattr(onchain, "_get", lambda url: DEX_RESPONSE)
    meta = onchain.resolve(f"solana:{CA}")
    assert meta["symbol"] == "ANSEM"
    assert meta["pool"] == "POOL1"  # max liquidity among *solana* pools only


def test_resolve_no_solana_pool_raises(monkeypatch):
    monkeypatch.setattr(onchain, "_get", lambda url: {"pairs": []})
    with pytest.raises(onchain.OnchainError):
        onchain.resolve(CA)


def _gt_response(rows):
    return {"data": {"attributes": {"ohlcv_list": rows}}}


def test_fetch_ohlcv_daily(monkeypatch):
    day = 86_400
    rows = [[3 * day, 4.0, 5.0, 3.0, 4.5, 100.0], [2 * day, 3.0, 4.0, 2.0, 3.5, 50.0]]

    def fake_get(url):
        if "dexscreener" in url:
            return DEX_RESPONSE
        assert "/ohlcv/day" in url
        return _gt_response(rows)

    monkeypatch.setattr(onchain, "_get", fake_get)
    df = onchain.fetch_ohlcv(f"solana:{CA}", "1d")
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert len(df) == 2
    assert df.index.is_monotonic_increasing  # API is newest-first; we sort
    assert float(df["close"].iloc[-1]) == 4.5


def test_fetch_ohlcv_weekly_resamples_daily(monkeypatch):
    day = 86_400
    rows = [[i * day, 1.0, 2.0, 0.5, 1.5, 10.0] for i in range(4, 18)]

    def fake_get(url):
        if "dexscreener" in url:
            return DEX_RESPONSE
        assert "/ohlcv/day" in url  # 1w has no native endpoint
        return _gt_response(rows)

    monkeypatch.setattr(onchain, "_get", fake_get)
    df = onchain.fetch_ohlcv(CA, "1w")
    assert 2 <= len(df) <= 4
    assert float(df["volume"].iloc[0]) > 10.0  # summed, not sampled


def test_registry_resolves_bare_ca_without_alias():
    registry = Registry({"stopwords": []})
    m = registry.resolve(CA, "llm", "text")
    assert m.resolved_symbol == f"solana:{CA}"
    assert m.asset_class == "onchain"
    assert m.confidence == 1.0


def test_extract_contracts_pass():
    ms = extract_contracts(f"aping {CA} rn", "text")
    assert len(ms) == 1
    assert ms[0].resolved_symbol == f"solana:{CA}"
    assert ms[0].method == "contract"
