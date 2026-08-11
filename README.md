# X Signal Tracker

Daily pipeline that watches a curated X (Twitter) List of trader accounts,
extracts every asset they mention, charts each one on the 1D timeframe with
Supertrend(22,3) and monthly Swing CPR, and states a mechanical verdict — one
static HTML page per day, plus an optional Telegram digest.

It automates a loop otherwise run by hand: trusted account posts about an
asset → pull up the chart → check trend and pivot structure → decide if the
call agrees with the indicators.

## How it works

1. **Ingest** ([src/ingest.py](src/ingest.py)) — fetch the last 24h of posts
   from an X List via `twitter-cli` (browser-cookie auth, read-only). Per-account
   retweet policy; loud failure on empty or invalid list results.
2. **Extract** ([src/extract.py](src/extract.py)) — five passes per tweet:
   cashtags, registry keywords, LLM prose extraction, quoted-tweet text, and
   vision on attached chart images. LLM backend is `claude -p` headless (runs on
   a Claude subscription) or the Anthropic SDK. Resolution is registry-only —
   no fuzzy matching, ever.
3. **Prices** ([src/prices.py](src/prices.py)) — crypto daily bars via CCXT
   (Binance → Bybit → OKX fallback), everything else via yfinance.
4. **Indicators** ([src/indicators.py](src/indicators.py)) — Supertrend(22,3)
   with Wilder ATR (seeded like Pine's `ta.rma`) and calendar-monthly Swing CPR
   (pivot, BC, TC, R1, S1). Reproduces TradingView values to 0.00001%.
5. **Verdict** ([src/verdict.py](src/verdict.py)) — a 2×3 grid of Supertrend
   direction × price-vs-CPR-band, with narrow/inverted-CPR badges.
6. **Persist** ([src/db.py](src/db.py)) — SQLite: tweets, mentions, and a
   same-day price/indicator snapshot per mention (entry price at time-of-post is
   unrecoverable later).
7. **Outcomes** ([src/outcomes.py](src/outcomes.py)) — 7/30/90-day forward
   returns per mention and a per-source scoreboard.
8. **Render** ([src/render.py](src/render.py), [src/chart.py](src/chart.py)) —
   one HTML page with inline SVG candlestick charts; PNG charts via Pillow for
   the Telegram digest ([src/telegram.py](src/telegram.py)).

## Setup

```bash
uv sync
cp config/settings.example.yaml config/settings.yaml   # fill in your List ID and accounts
```

Requires `twitter-cli` with a logged-in browser session for List access, and
`uv` for Python.

Optional `.env` (gitignored):

```
TELEGRAM_BOT_TOKEN=...   # enables the daily digest + failure alerts
TELEGRAM_CHAT_ID=...
ANTHROPIC_API_KEY=...    # only if extraction.backend: api
```

## Run

```bash
./run-daily.sh           # one full run; writes out/dist.html and out/run.log
./install-cron.sh        # install the 07:00 daily launchd job (macOS)
uv run pytest            # 102 tests
```

`install-cron.sh` generates a launcher under `~/.local/bin` that inlines the
run — required on macOS when the project lives in a TCC-protected folder
(Desktop/Documents), where Full Disk Access does not survive a nested script
call. See [docs/specs/2026-08-06-x-signal-tracker-design.md](docs/specs/2026-08-06-x-signal-tracker-design.md)
for the full design, including the failure modes that shaped it.

## Design rules worth knowing

- **The X List is membership; config is policy.** A List member absent from
  config still gets tracked with defaults.
- **Registry-only symbol resolution.** A fuzzy matcher that turns an unknown
  token name into a listed symbol renders a confident wrong chart; unresolved
  mentions land in a visible work queue instead.
- **A failed run must never look like a quiet news day.** Empty ingest raises;
  the cron wrapper alerts on non-zero exit.

## Disclaimer

This is a chart-annotation tool, not financial advice. Verdicts are mechanical
indicator readings, not recommendations.
