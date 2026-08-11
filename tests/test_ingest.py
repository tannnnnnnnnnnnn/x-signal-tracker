"""Spec §11 — ingest must never treat `author` as a membership check."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ingest import approving_account, filter_tweets, normalise

NOW = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)

CFG = {
    "x": {"lookback_hours": 24},
    "accounts": [
        {"handle": "YuvrajShah02", "include_retweets": True},
        {"handle": "blknoiz06", "include_retweets": False},
        {"handle": "DidiTrading", "include_retweets": True},
    ],
}


def tweet(tid, author, *, rt_by=None, hours_ago=1, text="hi", media=None, quoted=None):
    return {
        "id": str(tid),
        "author": {"screenName": author},
        "isRetweet": rt_by is not None,
        "retweetedBy": rt_by,
        "createdAtISO": (NOW - timedelta(hours=hours_ago)).isoformat(),
        "text": text,
        "media": [{"url": m} for m in (media or [])],
        "quotedTweet": {"text": quoted} if quoted else None,
    }


def test_approving_account_prefers_retweeter():
    assert approving_account(tweet(1, "josbjohnson", rt_by="blknoiz06")) == "blknoiz06"
    assert approving_account(tweet(2, "YuvrajShah02")) == "YuvrajShah02"


def test_list_member_absent_from_config_is_kept_and_reported():
    """The List is membership; config is policy only (spec §3.1).

    @Bluntz_Capital was a real List member missing from config. Dropping such a
    handle loses a genuine account silently.
    """
    kept, stats = filter_tweets([tweet(1, "Bluntz_Capital")], CFG, NOW)
    assert len(kept) == 1
    assert stats["unconfigured_handles"] == ["Bluntz_Capital"]


def test_unconfigured_member_defaults_to_keeping_retweets():
    kept, _ = filter_tweets([tweet(1, "ColeGotTweets", rt_by="Bluntz_Capital")], CFG, NOW)
    assert len(kept) == 1
    assert kept[0]["handle"] == "Bluntz_Capital"


def test_silent_handles_are_reported():
    """@wronguser000 posting nothing must be visible, not invisible."""
    _, stats = filter_tweets([tweet(1, "DidiTrading")], CFG, NOW)
    assert "YuvrajShah02" in stats["silent_handles"]
    assert "DidiTrading" not in stats["silent_handles"]


def test_ansem_retweets_dropped_but_own_posts_kept():
    raw = [
        tweet(1, "josbjohnson", rt_by="blknoiz06"),
        tweet(2, "Kaiz_294", rt_by="blknoiz06"),
        tweet(3, "blknoiz06", text="sol looking good"),
    ]
    kept, stats = filter_tweets(raw, CFG, NOW)
    assert [k["id"] for k in kept] == ["3"]
    assert stats["retweet_filtered"] == 2


def test_other_accounts_keep_their_retweets():
    raw = [tweet(1, "someone", rt_by="YuvrajShah02")]
    kept, _ = filter_tweets(raw, CFG, NOW)
    assert len(kept) == 1
    assert kept[0]["handle"] == "YuvrajShah02"
    assert kept[0]["author_handle"] == "someone"
    assert kept[0]["is_retweet"] is True


def test_lookback_window():
    raw = [tweet(1, "DidiTrading", hours_ago=30), tweet(2, "DidiTrading", hours_ago=2)]
    kept, stats = filter_tweets(raw, CFG, NOW)
    assert [k["id"] for k in kept] == ["2"]
    assert stats["too_old"] == 1


def test_unparseable_timestamp_is_kept_not_dropped():
    """Spec §10: a parse failure must not masquerade as a quiet day."""
    bad = tweet(1, "DidiTrading")
    bad["createdAtISO"] = "not-a-date"
    kept, stats = filter_tweets([bad], CFG, NOW)
    assert len(kept) == 1
    assert stats["too_old"] == 0


def test_normalise_captures_quoted_text_and_media():
    t = tweet(1, "IncomeSharks", text="Gold making the correction decision.",
              media=["https://pbs.twimg.com/media/x.jpg"], quoted="SBI fired")
    row = normalise(t, "2026-08-06T12:00:00+00:00")
    assert row["quoted_text"] == "SBI fired"
    assert row["media_urls"] == ["https://pbs.twimg.com/media/x.jpg"]
    assert row["url"] == "https://x.com/IncomeSharks/status/1"


def test_stats_account_for_every_input():
    raw = [
        tweet(1, "josbjohnson", rt_by="YuvrajShah02"),  # retweet, policy allows
        tweet(2, "Kaiz_294", rt_by="blknoiz06"),       # retweet filtered
        tweet(3, "DidiTrading", hours_ago=48),         # too old
        tweet(4, "DidiTrading"),                       # kept
    ]
    _, s = filter_tweets(raw, CFG, NOW)
    assert s["raw"] == 4
    assert s["retweet_filtered"] + s["too_old"] + s["kept"] == 4


def test_empty_list_is_fatal_not_a_quiet_day():
    """`ok: true, data: []` from a dead list must abort, never render an empty page.

    Verified against twitter-cli: list ID 999999999999 returns success with no
    rows. The endpoint ignores age, so zero rows means broken, not quiet.
    """
    import json as _json
    import subprocess
    from unittest.mock import patch

    from ingest import IngestError, fetch_list

    fake = subprocess.CompletedProcess(
        args=[], returncode=0,
        stdout=_json.dumps({"ok": True, "schema_version": "1", "data": []}), stderr="",
    )
    with patch("ingest.subprocess.run", return_value=fake):
        with pytest.raises(IngestError, match="not a quiet day"):
            fetch_list({"x": {"list_id": "999999999999"}})


def test_quiet_day_renders_rather_than_aborting():
    """Raw tweets present but all outside the window is a real quiet day."""
    kept, stats = filter_tweets([tweet(1, "DidiTrading", hours_ago=99)], CFG, NOW)
    assert kept == []
    assert stats["raw"] == 1 and stats["too_old"] == 1
