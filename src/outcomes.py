"""Forward-return scoring and the source scoreboard. Spec §9, Phase 6.

This is the part that answers the question the feed alone cannot: over time,
which accounts are actually right, and does the indicator verdict beat them.

The entry price is captured at snapshot time and is unrecoverable afterwards,
which is why snapshots are written from day one even though the reporting side
only becomes meaningful after a month of history.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pandas as pd

import prices

HORIZONS = (7, 30, 90)


def _asset_class(conn: sqlite3.Connection, symbol: str) -> str:
    row = conn.execute(
        "SELECT asset_class FROM mentions WHERE resolved_symbol = ? AND asset_class IS NOT NULL LIMIT 1",
        (symbol,),
    ).fetchone()
    return row["asset_class"] if row else "crypto"


def evaluate(conn: sqlite3.Connection, today: datetime | None = None) -> dict:
    """Fill in forward returns for every snapshot old enough to have one."""
    today = (today or datetime.now(timezone.utc)).date()
    pending = conn.execute(
        """SELECT s.id, s.symbol, s.asof_date, s.close
           FROM snapshots s
           WHERE EXISTS (
             SELECT 1 FROM (SELECT ? AS h UNION SELECT ? UNION SELECT ?) hs
             WHERE NOT EXISTS (
               SELECT 1 FROM outcomes o WHERE o.snapshot_id = s.id AND o.horizon_days = hs.h
             )
           )""",
        HORIZONS,
    ).fetchall()

    stats = {"checked": len(pending), "written": 0, "symbols_failed": 0}
    cache: dict[str, pd.DataFrame] = {}
    now = datetime.now(timezone.utc).isoformat()

    for row in pending:
        asof = pd.Timestamp(row["asof_date"])
        due = [h for h in HORIZONS if (today - asof.date()).days >= h]
        if not due:
            continue

        if row["symbol"] not in cache:
            try:
                cache[row["symbol"]] = prices.fetch(
                    row["symbol"], _asset_class(conn, row["symbol"]), 500
                )
            except Exception:
                stats["symbols_failed"] += 1
                cache[row["symbol"]] = pd.DataFrame()
        df = cache[row["symbol"]]
        if df.empty:
            continue

        for h in due:
            target = asof + pd.Timedelta(days=h)
            future = df[df.index >= target]
            if future.empty:
                continue  # not enough history yet; retried on a later run
            fwd = (float(future["close"].iloc[0]) - row["close"]) / row["close"]
            conn.execute(
                """INSERT OR REPLACE INTO outcomes
                   (snapshot_id, horizon_days, fwd_return, evaluated_at)
                   VALUES (?,?,?,?)""",
                (row["id"], h, fwd, now),
            )
            stats["written"] += 1

    conn.commit()
    return stats


def scoreboard(conn: sqlite3.Connection, horizon: int = 30) -> list[dict]:
    """Per-account hit rate at one horizon.

    A call "hits" when the forward return moved the way the verdict said. Neutral
    and conflict verdicts are excluded — they made no directional claim, so
    scoring them either way would be dishonest.
    """
    rows = conn.execute(
        """SELECT t.handle, s.verdict, o.fwd_return
           FROM outcomes o
           JOIN snapshots s ON s.id = o.snapshot_id
           JOIN mentions  m ON m.id = s.mention_id
           JOIN tweets    t ON t.id = m.tweet_id
           WHERE o.horizon_days = ? AND s.verdict != 'Conflict'""",
        (horizon,),
    ).fetchall()

    agg: dict[str, dict] = {}
    for r in rows:
        a = agg.setdefault(r["handle"], {"handle": r["handle"], "n": 0, "hits": 0, "total_return": 0.0})
        bullish = r["verdict"].startswith(("Strong bullish", "Bullish"))
        signed = r["fwd_return"] if bullish else -r["fwd_return"]
        a["n"] += 1
        a["hits"] += int(signed > 0)
        a["total_return"] += signed

    out = []
    for a in agg.values():
        out.append({
            **a,
            "hit_rate": a["hits"] / a["n"] if a["n"] else 0.0,
            "avg_return": a["total_return"] / a["n"] if a["n"] else 0.0,
        })
    return sorted(out, key=lambda x: (-x["n"], -x["hit_rate"]))
