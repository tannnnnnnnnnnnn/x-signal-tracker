"""X List ingestion with retweet filtering, per spec §6 step 1.

The critical rule: `author` is NOT a membership check. Retweets surface under the
original author's handle, so 29 unapproved handles reached the sample feed in
§3.1.1. The approving account is `retweetedBy` when `isRetweet`, else `author`.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

CONFIG = Path(__file__).resolve().parent.parent / "config" / "settings.yaml"


class IngestError(RuntimeError):
    """Raised on any condition that must abort the run loudly (spec §10)."""


def load_config(path: Path = CONFIG) -> dict:
    with open(path) as fh:
        return yaml.safe_load(fh)


def fetch_list(cfg: dict) -> list[dict]:
    """Call twitter-cli and return the raw tweet dicts."""
    x = cfg["x"]
    env = {
        **os.environ,
        "TWITTER_BROWSER": x.get("browser", "chrome"),
        "TWITTER_CHROME_PROFILE": x.get("chrome_profile", "Default"),
    }
    cmd = ["twitter", "list", str(x["list_id"]), "-n", str(x.get("max_tweets", 200)), "--json"]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=180)

    # twitter-cli prints progress to stdout before the JSON body.
    start = proc.stdout.find("{")
    if start == -1:
        raise IngestError(f"no JSON in twitter-cli output. stderr: {proc.stderr[-500:]}")

    try:
        payload = json.loads(proc.stdout[start:])
    except json.JSONDecodeError as exc:
        raise IngestError(f"malformed twitter-cli JSON: {exc}") from exc

    if not payload.get("ok"):
        err = payload.get("error", {})
        raise IngestError(f"twitter-cli {err.get('code', 'error')}: {err.get('message', payload)}")

    data = payload.get("data") or []

    # A nonexistent or unreadable list returns {"ok": true, "data": []} -- success
    # with nothing in it, which reads exactly like a quiet day. It is not one:
    # this endpoint returns the last N tweets regardless of age, so a live list
    # with members always returns rows. Zero means broken, and §10 requires that
    # be loud. A genuinely quiet day still returns older tweets, which the 24h
    # window in filter_tweets() then removes.
    if not data:
        raise IngestError(
            f"list {x['list_id']} returned zero tweets. The API reports success, so this "
            "is a broken or inaccessible list, revoked auth, or the wrong list ID -- "
            "not a quiet day. Page left untouched."
        )

    return data


def approving_account(tweet: dict) -> str:
    """Which approved account put this tweet in front of us."""
    if tweet.get("isRetweet") and tweet.get("retweetedBy"):
        return tweet["retweetedBy"]
    return tweet["author"]["screenName"]


def normalise(tweet: dict, fetched_at: str) -> dict:
    author = tweet["author"]["screenName"]
    media = [m.get("url") or m.get("mediaUrl") for m in (tweet.get("media") or [])]
    return {
        "id": tweet["id"],
        "handle": approving_account(tweet),
        "author_handle": author,
        "is_retweet": bool(tweet.get("isRetweet")),
        "posted_at": tweet.get("createdAtISO") or tweet.get("createdAt"),
        "text": tweet.get("text") or "",
        "quoted_text": (tweet.get("quotedTweet") or {}).get("text"),
        "media_urls": [m for m in media if m],
        "url": f"https://x.com/{author}/status/{tweet['id']}",
        "fetched_at": fetched_at,
    }


def filter_tweets(raw: list[dict], cfg: dict, now: datetime | None = None) -> tuple[list[dict], dict]:
    """Apply approval, retweet policy and the lookback window.

    Returns (kept, stats). Stats feed the run summary so drops are never silent.
    """
    # The X List is the membership source of truth (spec §3.1); config carries
    # only per-account policy. A List member absent from config is legitimate and
    # gets the default policy -- dropping them would be a silent loss.
    policy = {a["handle"]: a.get("include_retweets", True) for a in cfg["accounts"]}
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=cfg["x"].get("lookback_hours", 24))
    fetched_at = now.isoformat()

    kept: list[dict] = []
    stats = {
        "raw": len(raw), "retweet_filtered": 0, "too_old": 0, "kept": 0,
        "unconfigured_handles": set(),
    }

    for t in raw:
        approver = approving_account(t)
        if approver not in policy:
            stats["unconfigured_handles"].add(approver)
        if t.get("isRetweet") and not policy.get(approver, True):
            stats["retweet_filtered"] += 1
            continue

        row = normalise(t, fetched_at)
        try:
            posted = datetime.fromisoformat(str(row["posted_at"]).replace("Z", "+00:00"))
            if posted.tzinfo is None:
                posted = posted.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            posted = now  # unparseable timestamp: keep rather than silently drop
        if posted < cutoff:
            stats["too_old"] += 1
            continue

        kept.append(row)

    stats["kept"] = len(kept)
    stats["unconfigured_handles"] = sorted(stats["unconfigured_handles"])
    stats["silent_handles"] = sorted(set(policy) - {k["handle"] for k in kept})
    return kept, stats
