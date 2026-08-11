"""Spec §11 extraction traps. No network — the LLM passes are tested separately."""

from __future__ import annotations

import pytest

from extract import Mention, Registry, _symbol_candidates, dedupe, extract_cashtags


@pytest.fixture(scope="module")
def registry():
    return Registry.load()


# --- Registry resolution -------------------------------------------------------


def test_resolves_across_asset_classes(registry):
    cases = [
        ("btc", "BTC/USDT", "crypto"),
        ("NVDA", "NVDA", "us_equity"),
        ("gold", "GC=F", "commodity_fx"),
        ("sbi", "SBIN.NS", "in_equity"),
        ("nifty", "^NSEI", "in_equity"),
    ]
    for token, symbol, asset_class in cases:
        m = registry.resolve(token, "cashtag", "text")
        assert m.resolved_symbol == symbol
        assert m.asset_class == asset_class


def test_case_and_dollar_prefix_insensitive(registry):
    for token in ("BTC", "btc", "$BTC", "  Btc "):
        assert registry.resolve(token, "cashtag", "text").resolved_symbol == "BTC/USDT"


def test_stopwords_produce_nothing(registry):
    for token in ("a", "the", "USD", "LFG", "ath"):
        assert registry.resolve(token, "cashtag", "text") is None


# --- The §11 traps -------------------------------------------------------------


def test_trap_gold_metal_vs_barrick_cashtag(registry):
    """'gold' is the metal; '$GLD' is the ETF. They must not collapse."""
    assert registry.resolve("gold", "llm", "text").resolved_symbol == "GC=F"
    assert registry.resolve("gld", "cashtag", "text").resolved_symbol == "GLD"


def test_trap_sol_spelled_out_matches_cashtag(registry):
    assert registry.resolve("solana", "llm", "text").resolved_symbol == "SOL/USDT"
    assert registry.resolve("$SOL", "cashtag", "text").resolved_symbol == "SOL/USDT"


def test_trap_bulksol_never_resolves_to_sol(registry):
    """The dangerous one: a fuzzy match would render a confident SOL chart."""
    m = registry.resolve("BulkSOL", "llm", "text")
    assert m.resolved_symbol is None, "must not chart anything"
    assert m.subject == "BulkSOL", "must still be nameable -> no-chart card"

    yt = registry.resolve("YT-BulkSOL", "llm", "text")
    assert yt.resolved_symbol is None
    assert yt.subject == "YT-BulkSOL (Exponent)"


def test_trap_unknown_token_is_unresolved_not_wrong(registry):
    m = registry.resolve("ZZQQ", "llm", "text")
    assert m.resolved_symbol is None
    assert m.subject is None
    assert m.confidence == 0.0


def test_trap_tweet_with_no_asset(registry):
    assert extract_cashtags("gm everyone, feeling good today", registry, "text") == []


def test_didi_subjects_are_named_not_charted(registry):
    for token in ("polymarket", "exponent", "aura", "perpl"):
        m = registry.resolve(token, "llm", "text")
        assert m.subject is not None
        assert m.resolved_symbol is None


# --- Cashtag pass --------------------------------------------------------------


def test_cashtag_extraction(registry):
    text = "long $BTC and $NVDA here, also watching $ZZQQ"
    found = {m.raw_token.upper(): m for m in extract_cashtags(text, registry, "text")}
    assert found["BTC"].resolved_symbol == "BTC/USDT"
    assert found["NVDA"].resolved_symbol == "NVDA"
    assert found["ZZQQ"].resolved_symbol is None


def test_cashtag_ignores_bare_prose(registry):
    """No $ means the regex must not fire; that is the prose pass's job."""
    assert extract_cashtags("bitcoin looks strong", registry, "text") == []


def test_cashtag_handles_empty_and_none(registry):
    assert extract_cashtags("", registry, "text") == []
    assert extract_cashtags(None, registry, "text") == []


# --- Vision symbol normalisation ----------------------------------------------


@pytest.mark.parametrize(
    "header,expected",
    [
        ("BTCUSDT", "BTC/USDT"),
        ("Bitcoin / TetherUS", "BTC/USDT"),
        ("XAUUSD", "GC=F"),
        ("NIFTY", "^NSEI"),
    ],
)
def test_vision_header_normalisation(registry, header, expected):
    resolved = None
    for candidate in _symbol_candidates(header):
        m = registry.resolve(candidate, "vision", "image")
        if m and m.resolved_symbol:
            resolved = m.resolved_symbol
            break
    assert resolved == expected


def test_symbol_candidates_strips_quote_currency():
    assert "BTC" in _symbol_candidates("BTCUSDT")
    assert "SOL" in _symbol_candidates("SOL/USDT")
    assert "BTC" in _symbol_candidates("BTC-PERP")


# --- Dedupe --------------------------------------------------------------------


def test_dedupe_prefers_cashtag_over_llm():
    cashtag = Mention("$BTC", "Bitcoin", "BTC/USDT", "crypto", "cashtag", "text", 1.0)
    llm = Mention("bitcoin", "Bitcoin", "BTC/USDT", "crypto", "llm", "text", 1.0)
    out = dedupe([llm, cashtag])
    assert len(out) == 1
    assert out[0].method == "cashtag"


def test_dedupe_keeps_distinct_symbols():
    a = Mention("$BTC", "Bitcoin", "BTC/USDT", "crypto", "cashtag", "text", 1.0)
    b = Mention("$ETH", "Ethereum", "ETH/USDT", "crypto", "cashtag", "text", 1.0)
    assert len(dedupe([a, b])) == 2


def test_dedupe_prefers_resolved_over_unresolved():
    good = Mention("gold", "Gold", "GC=F", "commodity_fx", "llm", "text", 1.0)
    bad = Mention("gold", None, None, None, "vision", "image", 0.0)
    out = dedupe([bad, good])
    assert len(out) == 2, "different keys: unresolved keys on raw token"


# --- Keyword pass (deterministic, no-API fallback) -----------------------------


def test_keyword_finds_bare_prose(registry):
    from extract import extract_keywords
    text = "The corrections in gold and silver are over."
    syms = {m.resolved_symbol for m in extract_keywords(text, registry, "text")}
    assert syms == {"GC=F", "SI=F"}


def test_keyword_respects_word_boundaries(registry):
    from extract import extract_keywords
    assert extract_keywords("a golden opportunity", registry, "text") == []
    assert extract_keywords("resolana is not solana", registry, "text")[0].resolved_symbol == "SOL/USDT"


def test_keyword_excludes_ambiguous_terms(registry):
    from extract import extract_keywords
    assert extract_keywords("every shitcoin and coin pumping", registry, "text") == []
    assert extract_keywords("the meta is rotating", registry, "text") == []


def test_keyword_longest_match_wins(registry):
    from extract import extract_keywords
    out = extract_keywords("bought YT-BulkSOL today", registry, "text")
    assert [m.subject for m in out] == ["YT-BulkSOL (Exponent)"]


def test_keyword_never_invents_a_symbol(registry):
    from extract import extract_keywords
    for m in extract_keywords("random words with no assets at all", registry, "text"):
        assert m.resolved_symbol is None


def test_keyword_ignores_cashtags(registry):
    """$BTC is the cashtag pass's job; the negative lookbehind prevents a double."""
    from extract import extract_keywords
    assert extract_keywords("$btc", registry, "text") == []


# --- Punctuation-insensitive resolution ----------------------------------------


@pytest.mark.parametrize(
    "written,expected",
    [
        ("HDFC Bank", "HDFCBANK.NS"),
        ("ICICI Bank", "ICICIBANK.NS"),
        ("Dr. Reddy's Laboratories", "DRREDDY.NS"),
        ("Larsen & Toubro", "LT.NS"),
        ("Hitachi Energy India", "POWERINDIA.NS"),
        ("Apollo Hospitals", "APOLLOHOSP.NS"),
    ],
)
def test_normalised_resolution(registry, written, expected):
    """The LLM writes prose names; registry keys are compact. Both must meet."""
    assert registry.resolve(written, "llm", "text").resolved_symbol == expected


def test_normalisation_is_not_fuzzy_matching(registry):
    """Punctuation-stripping must not become distance matching.

    BulkSOL normalises to 'bulksol', which is its own registry key — it must
    still refuse to become SOL.
    """
    assert registry.resolve("BulkSOL", "llm", "text").resolved_symbol is None
    assert registry.resolve("Bitcoinn", "llm", "text").resolved_symbol is None
    assert registry.resolve("SOLANAA", "llm", "text").resolved_symbol is None


def test_normalised_match_is_marked_lower_confidence(registry):
    exact = registry.resolve("hdfcbank", "llm", "text")
    normed = registry.resolve("HDFC Bank", "llm", "text")
    assert exact.confidence == 1.0
    assert normed.confidence == 0.9


def test_pump_excluded_from_keyword_scan(registry):
    from extract import extract_keywords
    assert extract_keywords("everything is pumping today, nice pump", registry, "text") == []
    assert registry.resolve("$PUMP", "cashtag", "text").resolved_symbol == "PUMP/USDT"


# --- Incidental-mention gating (the "solana wallet functionality" trap) --------


def test_extract_prose_returns_incidental_keys(registry, monkeypatch):
    import extract as ex

    raw = '{"assets": [], "incidental": ["solana", "$ANSEM"], "sentiment": "neutral"}'
    monkeypatch.setattr(ex, "_cli_call", lambda *a, **k: raw)
    mentions, sentiment, incidental = ex.extract_prose(
        "i will ask for solana wallet functionality to give followers $ANSEM",
        registry, "text", "m")
    assert mentions == []
    assert "solana" in incidental
    assert "sol/usdt" in incidental  # resolved form too
    assert "ansem" in incidental


def test_market_view_wins_over_incidental(registry, monkeypatch):
    import extract as ex

    raw = '{"assets": ["solana"], "incidental": ["solana"], "sentiment": "bullish"}'
    monkeypatch.setattr(ex, "_cli_call", lambda *a, **k: raw)
    mentions, _, incidental = ex.extract_prose("sol chart looks ready", registry, "text", "m")
    assert mentions[0].resolved_symbol == "SOL/USDT"
    assert "sol/usdt" not in incidental and "solana" not in incidental


def test_drop_incidental_gates_text_hits_not_contracts(registry):
    from extract import drop_incidental, extract_contracts, extract_keywords

    ca = "9cRCn9rGT8V2imeM2BaKs13yhMEais3ruM3rPvTGpump"
    mentions = extract_keywords("solana wallet functionality", registry, "text")
    mentions += extract_contracts(f"send {ca}", "text")
    assert any(m.resolved_symbol == "SOL/USDT" for m in mentions)

    kept = drop_incidental(mentions, {"sol/usdt", "solana"})
    assert not any(m.resolved_symbol == "SOL/USDT" for m in kept)
    assert any(m.method == "contract" for m in kept)  # CA is deliberate, ungated


def test_drop_incidental_noop_without_llm_judgement(registry):
    from extract import drop_incidental, extract_keywords

    mentions = extract_keywords("solana wallet functionality", registry, "text")
    assert drop_incidental(mentions, set()) == mentions
