"""Accounts/tweets persistence."""

import db
def test_list_only_handle_gets_an_accounts_row(tmp_path):
    """A List member absent from config must not break the tweets FK."""
    conn = db.connect(tmp_path / "t.db")
    db.sync_accounts(conn, [{"handle": "known"}, {"handle": "tradinglord"}], "2026-08-12")
    assert db.insert_tweet(conn, {
        "id": "1", "handle": "tradinglord", "author_handle": "tradinglord",
        "is_retweet": False, "posted_at": "2026-08-12T00:00:00+00:00",
        "text": "hi", "quoted_text": None, "media_urls": [],
        "url": "https://x.com/tradinglord/status/1", "fetched_at": "2026-08-12",
    })
