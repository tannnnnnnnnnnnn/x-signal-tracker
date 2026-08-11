"""Spec §9 / Phase 6 — forward scoring and the source scoreboard."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

import db
import outcomes


class FakeMention:
    def __init__(self, symbol="BTC/USDT", asset_class="crypto"):
        self.raw_token = "$BTC"
        self.subject = "Bitcoin"
        self.resolved_symbol = symbol
        self.asset_class = asset_class
        self.method = "cashtag"
        self.source_field = "text"
        self.confidence = 1.0


def card(verdict="Strong bullish", close=100.0, symbol="BTC/USDT"):
    return {
        "symbol": symbol, "close": close, "st_value": 90.0,
        "cpr": {"pivot": 95.0, "bc": 94.0, "tc": 96.0, "r1": 105.0, "s1": 85.0,
                "prior_high": 110.0, "prior_low": 80.0, "width": 0.02, "period": "2026-07"},
        "verdict": {"verdict": verdict, "st_direction": "bull", "badges": ["narrow CPR"]},
    }


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    db.sync_accounts(c, [{"handle": "DidiTrading", "include_retweets": True}], "2026-08-01")
    c.execute(
        """INSERT INTO tweets (id, handle, author_handle, is_retweet, posted_at,
           text, url, fetched_at) VALUES ('1','DidiTrading','DidiTrading',0,
           '2026-07-01','long btc','http://x','2026-07-01')"""
    )
    return c


def test_snapshot_roundtrip(conn):
    mid = db.insert_mention(conn, "1", FakeMention())
    db.insert_snapshot(conn, mid, card(), "2026-07-01")
    row = conn.execute("SELECT * FROM snapshots").fetchone()
    assert row["symbol"] == "BTC/USDT"
    assert row["cpr_r1"] == 105.0
    assert row["narrow_cpr"] == 1
    assert row["inverted_cpr"] == 0


def test_snapshot_same_day_is_idempotent(conn):
    mid = db.insert_mention(conn, "1", FakeMention())
    db.insert_snapshot(conn, mid, card(), "2026-07-01")
    db.insert_snapshot(conn, mid, card(close=200.0), "2026-07-01")
    rows = conn.execute("SELECT close FROM snapshots").fetchall()
    assert len(rows) == 1 and rows[0]["close"] == 200.0


def test_evaluate_writes_forward_returns(conn, monkeypatch):
    mid = db.insert_mention(conn, "1", FakeMention())
    db.insert_snapshot(conn, mid, card(close=100.0), "2026-07-01")

    idx = pd.date_range("2026-07-01", periods=120, freq="D")
    fake = pd.DataFrame({"open": 100.0, "high": 100.0, "low": 100.0,
                         "close": [100.0 + i for i in range(120)]}, index=idx)
    monkeypatch.setattr(outcomes.prices, "fetch", lambda *a, **k: fake)

    stats = outcomes.evaluate(conn, today=datetime(2026, 11, 1, tzinfo=timezone.utc))
    assert stats["written"] == 3   # 7, 30, 90 all mature

    rows = {r["horizon_days"]: r["fwd_return"] for r in
            conn.execute("SELECT horizon_days, fwd_return FROM outcomes")}
    assert rows[7] == pytest.approx(0.07)
    assert rows[30] == pytest.approx(0.30)


def test_evaluate_skips_immature_horizons(conn, monkeypatch):
    mid = db.insert_mention(conn, "1", FakeMention())
    db.insert_snapshot(conn, mid, card(), "2026-07-01")
    idx = pd.date_range("2026-07-01", periods=120, freq="D")
    fake = pd.DataFrame({"open": 100.0, "high": 100.0, "low": 100.0,
                         "close": [100.0 + i for i in range(120)]}, index=idx)
    monkeypatch.setattr(outcomes.prices, "fetch", lambda *a, **k: fake)

    outcomes.evaluate(conn, today=datetime(2026, 7, 15, tzinfo=timezone.utc))
    horizons = [r["horizon_days"] for r in conn.execute("SELECT horizon_days FROM outcomes")]
    assert horizons == [7], "only the 7-day horizon has matured"


def test_scoreboard_scores_direction_not_raw_return(conn):
    """A bearish verdict that is followed by a fall is a HIT, not a miss."""
    mid = db.insert_mention(conn, "1", FakeMention())
    db.insert_snapshot(conn, mid, card(verdict="Strong bearish"), "2026-07-01")
    sid = conn.execute("SELECT id FROM snapshots").fetchone()["id"]
    conn.execute("INSERT INTO outcomes VALUES (?,30,?,?)", (sid, -0.10, "now"))

    board = outcomes.scoreboard(conn, 30)
    assert board[0]["handle"] == "DidiTrading"
    assert board[0]["hit_rate"] == 1.0
    assert board[0]["avg_return"] == pytest.approx(0.10)


def test_scoreboard_excludes_conflict_verdicts(conn):
    """Conflict makes no directional claim, so scoring it either way is dishonest."""
    mid = db.insert_mention(conn, "1", FakeMention())
    db.insert_snapshot(conn, mid, card(verdict="Conflict"), "2026-07-01")
    sid = conn.execute("SELECT id FROM snapshots").fetchone()["id"]
    conn.execute("INSERT INTO outcomes VALUES (?,30,?,?)", (sid, 0.10, "now"))
    assert outcomes.scoreboard(conn, 30) == []


def test_scoreboard_empty_on_fresh_db(conn):
    assert outcomes.scoreboard(conn, 30) == []
