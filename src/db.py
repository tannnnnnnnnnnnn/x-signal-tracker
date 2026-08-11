"""SQLite schema and helpers, per spec §9."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "tracker.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
  handle           TEXT PRIMARY KEY,
  added_at         TEXT NOT NULL,
  active           INTEGER NOT NULL DEFAULT 1,
  include_retweets INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS tweets (
  id            TEXT PRIMARY KEY,
  handle        TEXT NOT NULL REFERENCES accounts(handle),
  author_handle TEXT NOT NULL,
  is_retweet    INTEGER NOT NULL DEFAULT 0,
  posted_at     TEXT NOT NULL,
  text          TEXT NOT NULL,
  quoted_text   TEXT,
  media_urls    TEXT,
  url           TEXT NOT NULL,
  sentiment     TEXT,
  fetched_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mentions (
  id              INTEGER PRIMARY KEY,
  tweet_id        TEXT NOT NULL REFERENCES tweets(id),
  raw_token       TEXT NOT NULL,
  subject         TEXT,
  resolved_symbol TEXT,
  asset_class     TEXT,
  method          TEXT NOT NULL,
  source_field    TEXT NOT NULL,
  confidence      REAL,
  UNIQUE (tweet_id, raw_token)
);

CREATE TABLE IF NOT EXISTS snapshots (
  id            INTEGER PRIMARY KEY,
  mention_id    INTEGER NOT NULL REFERENCES mentions(id),
  symbol        TEXT NOT NULL,
  asof_date     TEXT NOT NULL,
  close         REAL NOT NULL,
  st_value      REAL NOT NULL,
  st_direction  TEXT NOT NULL,
  cpr_pivot     REAL NOT NULL,
  cpr_bc        REAL NOT NULL,
  cpr_tc        REAL NOT NULL,
  cpr_r1        REAL NOT NULL,
  cpr_s1        REAL NOT NULL,
  prior_high    REAL NOT NULL,
  prior_low     REAL NOT NULL,
  cpr_width     REAL NOT NULL,
  narrow_cpr    INTEGER NOT NULL,
  inverted_cpr  INTEGER NOT NULL,
  verdict       TEXT NOT NULL,
  conflict      INTEGER NOT NULL,
  UNIQUE (mention_id, asof_date)
);

CREATE TABLE IF NOT EXISTS outcomes (
  snapshot_id   INTEGER NOT NULL REFERENCES snapshots(id),
  horizon_days  INTEGER NOT NULL,
  fwd_return    REAL NOT NULL,
  evaluated_at  TEXT NOT NULL,
  PRIMARY KEY (snapshot_id, horizon_days)
);

CREATE INDEX IF NOT EXISTS idx_tweets_posted ON tweets(posted_at);
CREATE INDEX IF NOT EXISTS idx_mentions_tweet ON mentions(tweet_id);
"""


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def sync_accounts(conn: sqlite3.Connection, accounts: list[dict], now: str) -> None:
    """Upsert the config accounts. Handles not in config are deactivated."""
    handles = [a["handle"] for a in accounts]
    for a in accounts:
        conn.execute(
            """INSERT INTO accounts (handle, added_at, active, include_retweets)
               VALUES (?, ?, 1, ?)
               ON CONFLICT(handle) DO UPDATE SET
                 active = 1, include_retweets = excluded.include_retweets""",
            (a["handle"], now, int(a.get("include_retweets", True))),
        )
    if handles:
        placeholders = ",".join("?" * len(handles))
        conn.execute(f"UPDATE accounts SET active = 0 WHERE handle NOT IN ({placeholders})", handles)
    conn.commit()


def insert_mention(conn: sqlite3.Connection, tweet_id: str, m) -> int | None:
    """Upsert a mention, returning its row id."""
    conn.execute(
        """INSERT OR IGNORE INTO mentions
           (tweet_id, raw_token, subject, resolved_symbol, asset_class,
            method, source_field, confidence)
           VALUES (?,?,?,?,?,?,?,?)""",
        (tweet_id, m.raw_token, m.subject, m.resolved_symbol, m.asset_class,
         m.method, m.source_field, m.confidence),
    )
    row = conn.execute(
        "SELECT id FROM mentions WHERE tweet_id = ? AND raw_token = ?",
        (tweet_id, m.raw_token),
    ).fetchone()
    return row["id"] if row else None


def insert_snapshot(conn: sqlite3.Connection, mention_id: int, card: dict, asof: str) -> None:
    """One row per mention per day. Re-running the same day is idempotent."""
    c, v = card["cpr"], card["verdict"]
    conn.execute(
        """INSERT OR REPLACE INTO snapshots
           (mention_id, symbol, asof_date, close, st_value, st_direction,
            cpr_pivot, cpr_bc, cpr_tc, cpr_r1, cpr_s1, prior_high, prior_low,
            cpr_width, narrow_cpr, inverted_cpr, verdict, conflict)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (mention_id, card.get("_symbol") or card["symbol"], asof, card["close"], card["st_value"],
         v["st_direction"], c["pivot"], c["bc"], c["tc"], c["r1"], c["s1"],
         c["prior_high"], c["prior_low"], c["width"],
         int("narrow CPR" in v["badges"]), int("inverted CPR" in v["badges"]),
         v["verdict"], int(v["verdict"] == "Conflict")),
    )


def insert_tweet(conn: sqlite3.Connection, t: dict) -> bool:
    """Returns True when the row was new."""
    cur = conn.execute(
        """INSERT OR IGNORE INTO tweets
           (id, handle, author_handle, is_retweet, posted_at, text,
            quoted_text, media_urls, url, sentiment, fetched_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            t["id"], t["handle"], t["author_handle"], int(t["is_retweet"]),
            t["posted_at"], t["text"], t.get("quoted_text"),
            json.dumps(t.get("media_urls") or []), t["url"],
            t.get("sentiment"), t["fetched_at"],
        ),
    )
    return cur.rowcount > 0
