"""Telegram digest and the PNG renderer. No network — requests.post is patched."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import chart_png
import telegram
from indicators import supertrend, swing_cpr


@pytest.fixture
def sent(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    calls = []

    class R:
        ok = True
        status_code = 200
        text = "{}"

    def fake_post(url, data=None, files=None, timeout=None):
        calls.append({"url": url, "data": data, "files": files})
        return R()

    monkeypatch.setattr(telegram.requests, "post", fake_post)
    return calls


def card(symbol="BTC/USDT", verdict="Strong bullish", disagrees=False):
    return {
        "kind": "chart", "symbol": symbol, "handle": "DidiTrading",
        "url": "https://x.com/DidiTrading/status/1",
        "verdict": {"verdict": verdict, "badges": ["narrow CPR"]},
        "disagrees": disagrees,
    }


def test_not_configured_without_env(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert telegram.configured() is False


def test_digest_sends_one_summary_message(sent):
    telegram.send_digest([card()], [], {"kept": 5}, [])
    assert len(sent) == 1
    text = sent[0]["data"]["text"]
    assert "BTC/USDT" in text and "Strong bullish" in text and "narrow CPR" in text


def test_digest_flags_disagreement(sent):
    telegram.send_digest([card(disagrees=True)], [], {"kept": 1}, [])
    assert "disagrees" in sent[0]["data"]["text"]


def test_digest_reports_quiet_day_explicitly(sent):
    telegram.send_digest([], [], {"kept": 0}, [])
    assert "No assets mentioned" in sent[0]["data"]["text"]


def test_digest_surfaces_warnings(sent):
    telegram.send_digest([], [], {"kept": 0}, ["auth expiring soon"])
    assert "auth expiring soon" in sent[0]["data"]["text"]


def test_digest_escapes_html(sent):
    c = card(symbol="A&B<script>")
    telegram.send_digest([c], [], {"kept": 1}, [])
    assert "<script>" not in sent[0]["data"]["text"]
    assert "&lt;script&gt;" in sent[0]["data"]["text"]


def test_digest_sends_photos_when_renderer_given(sent):
    telegram.send_digest([card()], [], {"kept": 1}, [], png_for=lambda c: b"\x89PNG fake")
    assert len(sent) == 2
    assert sent[1]["files"]["photo"][0] == "chart.png"


def test_failed_photo_does_not_lose_the_digest(sent):
    def boom(c):
        raise RuntimeError("render failed")

    telegram.send_digest([card()], [], {"kept": 1}, [], png_for=boom)
    assert len(sent) == 1, "summary still sent"


def test_nochart_cards_listed(sent):
    nc = {"kind": "nochart", "subject": "YT-BulkSOL", "handle": "DidiTrading"}
    telegram.send_digest([nc], [], {"kept": 1}, [])
    assert "YT-BulkSOL" in sent[0]["data"]["text"]


# --- PNG renderer --------------------------------------------------------------


def test_png_renders_valid_image():
    rng = np.random.default_rng(3)
    n = 400
    close = 100 + np.cumsum(rng.normal(0, 1.5, n))
    df = pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close},
        index=pd.date_range("2024-01-01", periods=n, freq="D"),
    )
    png = chart_png.render_png(df, supertrend(df), swing_cpr(df), "BTC/USDT", "Strong bullish")
    assert png[:8] == b"\x89PNG\r\n\x1a\n", "valid PNG signature"
    assert len(png) > 4000
