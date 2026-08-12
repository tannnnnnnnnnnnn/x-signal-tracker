"""Daily pipeline. Spec §6.

Governing rule from §10: a failed run must never look like a quiet news day.
Fatal conditions abort before the page is rewritten; partial failures degrade
into visible banners.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import chart_png
import db
import extract
import ingest
import onchain
import outcomes
import prices
import render
import telegram
from indicators import cpr_history, cpr_width_history, ema, supertrend, swing_cpr
from verdict import judge, sentiment_disagrees


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# Interactive chart timeframes. 1D drives the verdict and snapshot; 4H and 1W
# are view-only and degrade gracefully when a venue or a young token lacks bars.
EXTRA_TIMEFRAMES = {"4h": 1000, "1w": 500}
EMA_PERIODS = (50, 200)


def _tf_series(df, st) -> dict:
    candles = [
        {"time": int(ts.timestamp()), "open": float(r["open"]), "high": float(r["high"]),
         "low": float(r["low"]), "close": float(r["close"])}
        for ts, r in df.iterrows()
    ]
    st_points = []
    if st is not None:
        for ts, r in st.series.dropna(subset=["supertrend"]).iterrows():
            st_points.append({"time": int(ts.timestamp()),
                              "value": float(r["supertrend"]), "dir": r["direction"]})
    emas = {}
    for period in EMA_PERIODS:
        series = ema(df["close"], period).dropna()
        emas[f"ema{period}"] = [
            {"time": int(ts.timestamp()), "value": float(v)} for ts, v in series.items()
        ]
    return {"candles": candles, "st": st_points, **emas}


def build_chart_data(symbol: str, asset_class: str, df_1d, st_1d, min_bars: int) -> dict:
    """Candles + supertrend for 1D/4H/1W, plus monthly CPR segments (from 1D)."""
    data = {"1d": _tf_series(df_1d, st_1d)}
    for tf, limit in EXTRA_TIMEFRAMES.items():
        try:
            df_tf = prices.fetch(symbol, asset_class, limit, timeframe=tf)
            try:
                st_tf = supertrend(df_tf)
            except ValueError:
                st_tf = None  # young token: fewer than ATR-period bars on this TF
            data[tf] = _tf_series(df_tf, st_tf)
        except Exception as exc:
            log(f"  {symbol} {tf} unavailable: {exc}")
    data["cpr"] = [
        {"start": int(seg["start"].timestamp()), "end": int(seg["end"].timestamp()),
         "pivot": seg["pivot"], "bc": seg["bc"], "tc": seg["tc"],
         "r1": seg["r1"], "s1": seg["s1"]}
        for seg in cpr_history(df_1d)
    ]
    return data


def build_cards(tweets: list[dict], registry: extract.Registry, cfg: dict,
                warnings: list[str]) -> tuple[list[dict], list[dict]]:
    backend = cfg["extraction"].get("backend", "claude_cli")
    llm_on = extract.backend_available(backend)
    if not llm_on:
        detail = (
            "the `claude` CLI is not on PATH"
            if backend == "claude_cli"
            else "ANTHROPIC_API_KEY is not set"
        )
        warnings.append(
            f"LLM extraction disabled — {detail}. Running cashtag + keyword matching "
            "only, so prose phrasing outside the registry and chart-image mentions "
            "will be missed. A short feed today may be under-extraction rather than "
            "a quiet day."
        )
    else:
        log(f"extraction backend: {backend}")

    model = cfg["extraction"]["model"]
    budget = cfg["extraction"].get("max_images_per_run", 60)
    workers = cfg["extraction"].get("workers", 4)
    vision_on = cfg["extraction"].get("vision", True)
    cards: list[dict] = []
    unresolved: list[dict] = []
    failures: list[str] = []
    image_budget = [budget]        # mutable box, shared across worker threads
    skipped_images = [0]
    budget_lock = threading.Lock()

    def extract_one(t: dict) -> tuple[dict, list, str | None]:
        """All extraction passes for one tweet. Runs in a worker thread."""
        mentions = extract.extract_cashtags(t["text"], registry, "text")
        mentions += extract.extract_cashtags(t.get("quoted_text") or "", registry, "quoted_text")
        mentions += extract.extract_keywords(t["text"], registry, "text")
        mentions += extract.extract_keywords(t.get("quoted_text") or "", registry, "quoted_text")
        mentions += extract.extract_contracts(t["text"], "text")
        mentions += extract.extract_contracts(t.get("quoted_text") or "", "quoted_text")
        sentiment = None

        if llm_on:
            combined = t["text"] + ("\n\n[quoted] " + t["quoted_text"] if t.get("quoted_text") else "")
            try:
                prose, sentiment, incidental = extract.extract_prose(
                    combined, registry, "text", model, backend)
                mentions += prose
                mentions = extract.drop_incidental(mentions, incidental)
            except Exception as exc:
                failures.append(f"prose {t['id']}: {exc}")

            for url in (t.get("media_urls") or [])[:2] if vision_on else []:
                with budget_lock:
                    if image_budget[0] <= 0:
                        skipped_images[0] += 1
                        continue
                    image_budget[0] -= 1
                try:
                    mentions += extract.extract_vision(url, registry, model, backend)
                except Exception as exc:
                    failures.append(f"vision {t['id']}: {exc}")

        return t, mentions, sentiment

    # The CLI backend costs ~10-15s per call, so 21 tweets serially is ~6 minutes.
    # A small pool keeps the daily run to a minute or two. Kept modest: these calls
    # draw on the same subscription quota, just faster.
    with ThreadPoolExecutor(max_workers=workers if llm_on else 1) as pool:
        results = list(pool.map(extract_one, tweets))
    log(f"extraction done for {len(results)} tweets, {len(failures)} call failure(s)")

    for t, mentions, sentiment in results:
        for m in extract.dedupe(mentions):
            base = {
                "handle": t["handle"], "author_handle": t["author_handle"],
                "is_retweet": t["is_retweet"], "text": t["text"],
                "quoted_text": t.get("quoted_text"), "url": t["url"],
                "when": str(t["posted_at"])[:16].replace("T", " "),
                "sentiment": sentiment,
            }

            if m.resolved_symbol is None:
                if m.subject:
                    cards.append({**base, "kind": "nochart", "subject": m.subject,
                                  "_tweet_id": t["id"], "_mention": m})
                else:
                    unresolved.append({**base, "raw_token": m.raw_token,
                                       "method": m.method, "source_field": m.source_field,
                                       "_tweet_id": t["id"], "_mention": m})
                continue

            try:
                display_symbol, display_name = m.resolved_symbol, m.subject
                if m.asset_class == "onchain":
                    meta = onchain.resolve(m.resolved_symbol)
                    display_symbol = f"${meta['symbol']}"
                    display_name = f"{meta['name']} · {meta['dex']}"
                df = prices.fetch(m.resolved_symbol, m.asset_class, cfg["prices"]["min_bars"])
                st = supertrend(df)
                cpr = swing_cpr(df)
                v = judge(float(df["close"].iloc[-1]), st, cpr, cpr_width_history(df))
                chart_data = build_chart_data(
                    m.resolved_symbol, m.asset_class, df, st, cfg["prices"]["min_bars"]
                )
            except Exception as exc:
                log(f"  price/indicator failure for {m.resolved_symbol}: {exc}")
                unresolved.append({**base, "raw_token": f"{m.raw_token} (data error: {exc})",
                                   "method": m.method, "source_field": m.source_field,
                                   "_tweet_id": t["id"], "_mention": m})
                continue

            cards.append({
                **base, "kind": "chart",
                "symbol": display_symbol, "name": display_name or display_symbol,
                "_symbol": m.resolved_symbol,  # canonical, refetchable (outcomes)
                "close": float(df["close"].iloc[-1]),
                "st_value": st.value,
                "cpr": {"pivot": cpr.pivot, "bc": cpr.bc, "tc": cpr.tc,
                        "r1": cpr.r1, "s1": cpr.s1,
                        "prior_high": cpr.prior_high, "prior_low": cpr.prior_low,
                        "width": cpr.width, "period": cpr.period_label},
                "verdict": {"verdict": v.verdict, "st_direction": v.st_direction,
                            "badges": v.badges},
                "disagrees": sentiment_disagrees(sentiment, v),
                "chart_data": chart_data,
                "_tweet_id": t["id"], "_mention": m, "_df": df, "_st": st, "_cpr": cpr,
            })

    if skipped_images[0]:
        # Spec §13: a silent cap reads as "covered everything" when it did not.
        warnings.append(
            f"{skipped_images[0]} chart image(s) skipped — hit the "
            f"max_images_per_run cap of {budget}."
        )
    if failures:
        warnings.append(
            f"{len(failures)} LLM extraction call(s) failed; recall is reduced today. "
            + "; ".join(failures[:3])
        )
    return cards, unresolved


def main() -> int:
    warnings: list[str] = []
    errors: list[str] = []

    cfg = ingest.load_config()
    registry = extract.Registry.load()

    try:
        raw = ingest.fetch_list(cfg)
    except ingest.IngestError as exc:
        # Fatal: do NOT rewrite the page. An empty page would read as a quiet day.
        log(f"FATAL: {exc}")
        print(f"\nFEED FAILED — page left untouched.\n{exc}", file=sys.stderr)
        return 1

    tweets, stats = ingest.filter_tweets(raw, cfg)
    log(f"ingest: {json.dumps(stats)}")

    if stats["unconfigured_handles"]:
        warnings.append(
            "In the List but not in config (default retweet policy applied): "
            + ", ".join("@" + h for h in stats["unconfigured_handles"])
        )
    if stats["silent_handles"]:
        warnings.append("No posts in 24h from: " + ", ".join("@" + h for h in stats["silent_handles"]))

    conn = db.connect()
    db.sync_accounts(conn, cfg["accounts"], datetime.now(timezone.utc).isoformat())
    new = sum(db.insert_tweet(conn, t) for t in tweets)
    conn.commit()
    log(f"stored {new} new tweets ({len(tweets) - new} already seen)")

    cards, unresolved = build_cards(tweets, registry, cfg, warnings)
    log(f"cards: {sum(c['kind'] == 'chart' for c in cards)} charted, "
        f"{sum(c['kind'] == 'nochart' for c in cards)} unchartable, "
        f"{len(unresolved)} unresolved")

    # Persist mentions and snapshots. The entry price at time-of-post is
    # unrecoverable later, which is the whole reason this runs before rendering.
    asof = datetime.now(timezone.utc).date().isoformat()
    saved = 0
    for item in cards + unresolved:
        mid = db.insert_mention(conn, item["_tweet_id"], item["_mention"])
        if mid and item.get("kind") == "chart":
            db.insert_snapshot(conn, mid, item, asof)
            saved += 1
    conn.commit()
    log(f"persisted {saved} snapshots for {asof}")

    ostats = outcomes.evaluate(conn)
    board = outcomes.scoreboard(conn, horizon=30)
    log(f"outcomes: {json.dumps(ostats)}; scoreboard rows: {len(board)}")

    out = render.render(cards, unresolved, stats, warnings, errors, board=board)
    log(f"wrote {out}")

    if telegram.configured():
        try:
            telegram.send_digest(
                cards, unresolved, stats, warnings,
                png_for=lambda c: chart_png.render_png(
                    c["_df"], c["_st"], c["_cpr"], c["symbol"], c["verdict"]["verdict"]
                ),
            )
            log("telegram digest sent")
        except Exception as exc:
            log(f"telegram digest failed: {exc}")   # never fatal; the page is written
    else:
        log("telegram not configured — skipping digest")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
