# X Signal Tracker — Design

**Date:** 2026-08-06
**Status:** approved 2026-08-06
**Owner:** Tanmay Shah

---

## 1. Purpose

Automate the loop Tanmay already runs by hand: a trusted X account posts about an
asset → look the asset up → apply his own 1D indicators → form a view.

The Exponent YT-BulkSOL position is the reference case. @DidiTrading posted, the
post was acted on, and the post-mortem five days later did the analysis that
should have happened first. This system does that analysis on the morning of the
post, for every post, automatically.

Output is a daily page: one card per asset mentioned, showing the tweet, a 1D
chart with Supertrend and SwingCPR overlaid, and a mechanical verdict.

## 2. Non-goals

- **Portfolio or allocation tracking.** The liquidity review deferred on
  2026-07-19 (`AI Brain/wiki/topics/investing-finance.md`) is a separate system.
  This one ingests signals; it holds no positions and knows no balances.
- **Order execution.** Nothing here places a trade.
- **Financial advice.** Verdicts are deterministic indicator output.
- **Reimplementing TradingView.** Two indicators, one timeframe.

## 3. Decisions locked

| Decision | Value |
|---|---|
| Timeframe | 1D only |
| Indicator 1 | Supertrend, ATR 22, multiplier 3 |
| Indicator 2 | SwingCPR — pivot, BC, TC, R1, S1 (in plot order) |
| SwingCPR period | Calendar monthly (prior month's H/L/C) |
| Asset classes | Crypto, US equities + ETFs, commodities + FX, Indian equities |
| Cadence | Daily cron, including crypto |
| Delivery | Static web page + Telegram digest |
| Account source | Private X List `<list-id>` (membership); config carries retweet policy only |
| X account | `@<his-x-handle>` |
| X auth | Chrome cookie store, `TWITTER_BROWSER=chrome` + `TWITTER_CHROME_PROFILE=Default`. No stored tokens. |
| Chart rendering | Inline SVG for the page, Pillow PNG for Telegram (§12.1 deviations 1 and 3) |
| Crypto price data | CCXT, falling back binance → bybit → okx |
| Other price data | yfinance. Gold = `GC=F` (Q2) |
| Extraction reach | Cashtag + keyword + LLM prose + quoted text + vision on images. PDFs deferred |
| Unchartable assets | No-chart card, not silently bucketed |
| Storage | SQLite, from day one |
| Language | Python — matches the airdrop bot |
| LLM backend | `claude -p` headless on the Max subscription. No API key (§12.1 deviation 4) |

## 3.1 Approved accounts

**Runtime source of truth: private X List `<list-id>`**, edited in the
X app. This table records the seed, why each account is included, and its
retweet policy.

| Handle | Name | Primary asset classes | Signal form | `include_retweets` |
|---|---|---|---|---|
| `@YuvrajShah02` | Yuvraj Shah | Indian equities | Text, **PDF attachments**, quote-tweets | yes |
| `@IncomeSharks` | IncomeSharks | US equities, commodities | Short text + **chart image** | yes |
| `@blknoiz06` | Ansem | Crypto (majors, Solana) | Text | **no** |
| `@wronguser000` | WRONGUSER | Crypto, gold | Text | yes |
| `@DidiTrading` | Didi | Airdrops, farms, Polymarket | Text, **mostly unchartable** | yes |

Coverage check: all four asset classes from §3 are represented, which retires
the concern in §13 that Indian equities might see zero feed volume.

### 3.1.1 Measured baseline, 2026-08-06

60 tweets spanning ~19 hours, via `twitter list <list-id>`:

| Account | Own posts | Retweets | Share |
|---|---|---|---|
| `@blknoiz06` | 13 | 33 | 77% |
| `@YuvrajShah02` | 9 | 1 | 17% |
| `@IncomeSharks` | 4 | 0 | 7% |
| `@DidiTrading` | 1 | 0 | 2% |
| `@wronguser000` | 0 | 0 | 0% |

Three facts that shaped the design:

1. **A List does not enforce the approved set.** 34 of 60 items were retweets,
   surfacing under the *original* author's handle — 29 handles never approved.
   The API exposes `isRetweet` and `retweetedBy`, so this is filterable, but only
   because those fields are read. Ingest must not treat `author` as membership.
2. **Retweet volume is wildly uneven** — 33:1 between Ansem and everyone else,
   and sampling showed product promos and career quotes rather than calls. Hence
   the per-account flag rather than one global rule.
3. **23 of 60 posts carry media**, projecting to ~29 vision calls/day. At Haiku
   rates this is cents per day; the cost concern raised against Q3 is not real.

Projected daily volume: ~75 raw items, ~27 own-posts, ~40 after retweet
filtering.

**Resolved 2026-08-06:** `@wronguser000` is confirmed in the List and simply
dormant — zero posts across 200 fetched tweets. Runs now emit `silent_handles`
so a quiet account is visible rather than invisible.

**Also found:** the List has a sixth member, **`@Bluntz_Capital`**, not in the
original five. Retweets on. This is why config cannot be the approval set — see
§6 step 1.

## 4. Open questions

**Q1 — SwingCPR period. RESOLVED 2026-08-06: calendar monthly.** Confirmed by
reproducing all five plotted BTCUSDT values from Binance's July 2026 daily bars
(H 66,956.15, L 57,800.19, C 62,887.88) to within 0.00001%. Prior period = July
2026; levels hold for the whole of August and step on the 1st.

*(An earlier version of this answer reached the right period through wrong
reasoning — see the correction note in §7.2.)*

**Q2 — gold symbol. RESOLVED 2026-08-10: keep `GC=F`.**

The gold screenshot turned out to be months old, not same-day: its session candle
matches 2026-04-28, and its CPR levels derive from **March 2026**, not July. Once
compared against the right month, `GC=F` reproduces all five plotted levels to
**0.302% mean error** — the CFD-vs-futures basis, not a logic fault. Spot-backed
`PAXG/USDT` was tested as the alternative and did worse (0.630%). `XAUUSD=X` and
`XAU=X` do not exist on Yahoo.

Two side effects worth recording. The gold fixture independently confirms the
monthly period **and** the inverted orientation, so Q1 now rests on two
unrelated instruments. And the residual 0.3% means gold levels on the page will
never exactly equal the TVC chart; that is expected, not a bug.

**Q3 — media and quoted-text extraction. RESOLVED (see below).** Two of the five
seed accounts put the call somewhere §6 does not look:

- `@YuvrajShah02` posted `🤝🤝` quote-tweeting a reply reading *"Sbi fired, one
  of the four shares your shared in the pdf"*. The ticker is in a **PDF**; the
  confirmation is in **quoted text**. Text-only extraction returns nothing.
- `@IncomeSharks` posts one line plus a **chart image**. "Gold making the
  correction decision." happens to name the asset, but the common form is a bare
  reaction plus a chart.

Three tiers, decide before Phase 2:

1. **Quoted text + reply chain** — cheap, no vision, purely more text to scan.
   Recovers the Yuvraj case partially. Do this regardless.
2. **Vision pass on attached images** — Haiku vision over chart screenshots to
   read the symbol off the chart header. Adds per-image cost and latency.
3. **PDF parsing** — attachment download plus text extraction. Narrowest payoff,
   most work, and only `@YuvrajShah02` needs it.

**RESOLVED 2026-08-06: tiers 1 and 2 are in scope for v1. Tier 3 (PDF) is
deferred.** Both land in Phase 2. Revisit PDF parsing only if Yuvraj's PDFs
prove to be where his good calls live — which the unresolved bucket will show.

**Q4 — unchartable assets. RESOLVED (see below).** `@DidiTrading` is the account whose post
drove a real position (Exponent YT-BulkSOL), and his subject matter — farm
tokens, Exponent yield markets, Polymarket outcomes — has **no OHLCV feed on any
source in §5**. Under the current design every Didi post lands in the unresolved
bucket and produces no card. The highest-signal account is the worst served.

**RESOLVED 2026-08-06: add a no-chart card type.** Renders the tweet and the
extracted subject with no indicators and no verdict. Keeps the highest-signal
account prominent instead of buried, and requires no price feed that does not
exist. See §9.1 for the resulting three card types.

## 5. Architecture

Six components, each independently testable.

```
                  ┌──────────────┐
  X private List →│  ingest.py   │→ tweets ──┐
                  └──────────────┘           │
                                             ▼
                  ┌──────────────┐    ┌─────────────┐
                  │  extract.py  │←───│  SQLite     │
                  │ cashtag+LLM  │───→│  tracker.db │
                  └──────────────┘    └─────────────┘
                                             ▲
                  ┌──────────────┐           │
  CCXT / yfinance→│  prices.py   │───────────┤
                  └──────────────┘           │
                                             │
                  ┌──────────────┐           │
                  │ indicators.py│───────────┤
                  │  ST + CPR    │           │
                  └──────────────┘           │
                                             ▼
                  ┌──────────────┐    ┌─────────────┐
                  │  render.py   │───→│ dist.html   │
                  │              │───→│ Telegram    │
                  └──────────────┘    └─────────────┘
```

Layout mirrors the existing `AI Brain/dashboard/` pattern — `state.json` holds
data, `index.html` the template, a build step emits a single self-contained
`dist.html`.

```
Financial Tracker/
├── docs/specs/
├── src/
│   ├── ingest.py        # X List → tweets
│   ├── extract.py       # tweets → resolved symbols
│   ├── prices.py        # symbol → OHLCV
│   ├── indicators.py    # OHLCV → Supertrend + SwingCPR
│   ├── verdict.py       # indicators → verdict
│   ├── render.py        # → dist.html + Telegram
│   └── db.py
├── config/
│   ├── aliases.yaml     # hand-maintained symbol resolution
│   └── settings.yaml
├── tests/
│   └── fixtures/        # golden indicator values
└── out/
    └── dist.html
```

## 6. Data flow

Daily at 07:00 IST:

1. **Ingest.** `twitter list <list-id> --json`, keep posts from the
   last 24h. Store raw. Deduplicate on tweet ID.

   **Retweet filtering runs here, not later.** For each item, the *approving*
   account is `retweetedBy` when `isRetweet` is true, otherwise `author`. Drop
   the item when that account's `include_retweets` is false (§3.1). Retweets that
   survive are attributed as "X retweeted @y" and stored with both handles.

   `author` is not a membership check — 29 unapproved handles appeared in the
   §3.1.1 sample purely via retweets.
2. **Extract.** Three passes per tweet:
   - Cashtag regex `\$[A-Za-z]{1,10}\b` over the tweet **and any quoted tweet**
     — high precision.
   - Claude Haiku over the tweet text plus quoted text for prose mentions
     ("long gold here", "bulksol") — high recall.
   - **Haiku vision over attached images**, reading the symbol from the chart
     header. Only runs when the post has an image attachment; skipped otherwise
     to bound cost.

   Union the results, resolve each raw token to a canonical symbol via
   `aliases.yaml`. Anything unresolved lands in a visible bucket on the page.
   **Never silently dropped.**

   PDF attachments are out of scope for v1 (Q3). A post whose only content is a
   PDF yields an unresolved entry naming the attachment, so the miss is visible.
3. **Fetch.** For each resolved symbol, pull ≥500 daily bars (~2 years, ~24
   monthly CPR periods). This covers the ATR-22 warmup with wide margin and the
   trailing 6-month CPR-width average from §8, with enough surplus that a
   partial-history symbol (a recently listed token) still produces a valid
   narrow-CPR flag.
4. **Compute.** Supertrend(22, 3) and SwingCPR on the daily series.
5. **Judge.** Apply the verdict grid. Compare against tweet sentiment.
6. **Render.** Build `dist.html`; send a Telegram digest with one PNG per card.
7. **Persist.** Write the full snapshot to SQLite for the scoreboard.

## 7. Indicator math

Implementations differ between libraries. These are normative.

### 7.1 Supertrend (ATR 22, multiplier 3)

ATR uses **Wilder's smoothing (RMA)**, not SMA or EMA — this is what
TradingView's built-in uses, and getting it wrong shifts every value.

```
hl2         = (high + low) / 2
basicUpper  = hl2 + 3 * ATR22
basicLower  = hl2 - 3 * ATR22

finalUpper[i] = basicUpper[i] < finalUpper[i-1] or close[i-1] > finalUpper[i-1]
                ? basicUpper[i] : finalUpper[i-1]
finalLower[i] = basicLower[i] > finalLower[i-1] or close[i-1] < finalLower[i-1]
                ? basicLower[i] : finalLower[i-1]

direction[i]  = close[i] > finalUpper[i-1] ? UP
              : close[i] < finalLower[i-1] ? DOWN
              : direction[i-1]

supertrend[i] = direction[i] == UP ? finalLower[i] : finalUpper[i]
```

### 7.2 SwingCPR

Period is **calendar monthly** (Q1, resolved). Inputs are the prior calendar
month's high, low, and close; the levels hold constant for the whole of the
current month and step on the 1st.

```
pivot    = (H + L + C) / 3
bc       = (H + L) / 2
tc       = 2 * pivot - bc
r1       = 2 * pivot - L
s1       = 2 * pivot - H
cprWidth = abs(tc - bc) / pivot
```

Five lines are plotted, in this order: **pivot, BC, TC, R1, S1**.

**Corrected 2026-08-06.** An earlier revision of this section claimed lines 4
and 5 were the prior high and low, and that the order was pivot/TC/BC. Both were
wrong. Verified by reproducing all five plotted BTCUSDT values from Binance's
July 2026 bars to within 0.00001%.

> **Do not use `(r1 + s1) / 2 == tc` to identify lines.** That identity holds for
> every CPR by algebra — `(2p−L + 2p−H)/2 = 2p − BC = TC`. It was the basis of
> the original mistake: it confirmed on both fixtures, as it confirms on all
> input, and was read as evidence that line 3 was BC. A check that cannot fail
> is not a check. `tests/test_indicators.py::test_r1_s1_midpoint_identity_is_vacuous`
> is the regression guard.

Identities asserted in tests:

- `tc - pivot == pivot - bc`
- `(priorHigh + priorLow) / 2 == bc`
- `r1 == 2*pivot - priorLow` and `s1 == 2*pivot - priorHigh`
- `r1 != priorHigh` and `s1 != priorLow` — the mistake, stated as a test

## 8. Verdict

Supertrend state: `close > supertrend` → **bull**, else **bear**.

CPR position is defined by **band edges, never by the TC/BC labels**:

```
cprTop    = max(tc, bc)
cprBottom = min(tc, bc)

close > cprTop                      → above
cprBottom <= close <= cprTop        → inside
close < cprBottom                   → below
```

This matters because **TC and BC invert**. When the prior period closes below
`(H+L)/2`, the pivot falls below BC and therefore `tc < bc`. Any rule written as
`bc <= close <= tc` misclassifies every inverted period. **The gold fixture in
§11 is inverted; BTCUSDT is not** — which is precisely why two fixtures are
required and one is not enough.

| | Above TC | Inside CPR | Below BC |
|---|---|---|---|
| **ST bull** | Strong bullish | Bullish, indecisive | **Conflict** |
| **ST bear** | **Conflict** | Bearish, indecisive | Strong bearish |

Three modifiers:

- **Narrow CPR** — flagged when `cprWidth` is below its own trailing 6-period
  average. Signals an expected breakout; shown as a badge, does not change the
  verdict.
- **Inverted CPR** — flagged when `tc < bc`. Conventional CPR reading treats
  inversion as a bearish structural bias, independent of where price sits. Shown
  as a badge; does not change the verdict.
- **Source disagreement** — the tweet's own directional sentiment (Haiku,
  three-way: bullish / bearish / neutral) compared against the verdict.
  Disagreement is rendered prominently.

That last one is the point of the system. "Didi is long SOL, your indicators say
bearish" is the only line on the page that neither the tweet nor the chart
produces alone.

## 9. Data model

```sql
CREATE TABLE accounts (
  handle           TEXT PRIMARY KEY,
  added_at         TEXT NOT NULL,
  active           INTEGER NOT NULL DEFAULT 1,
  include_retweets INTEGER NOT NULL DEFAULT 1   -- 0 for @blknoiz06, see §3.1
);

CREATE TABLE tweets (
  id            TEXT PRIMARY KEY,    -- X tweet ID
  handle        TEXT NOT NULL REFERENCES accounts(handle),
                                     -- the APPROVING account: retweetedBy when
                                     -- isRetweet, else author. Never the raw
                                     -- author of a retweeted post.
  author_handle TEXT NOT NULL,       -- original author; differs on retweets
  is_retweet    INTEGER NOT NULL DEFAULT 0,
  posted_at     TEXT NOT NULL,
  text          TEXT NOT NULL,
  quoted_text   TEXT,                -- Q3 tier 1
  media_urls    TEXT,                -- JSON array; drives the vision pass
  url           TEXT NOT NULL,
  sentiment     TEXT,                -- bullish | bearish | neutral
  fetched_at    TEXT NOT NULL
);

CREATE TABLE mentions (
  id              INTEGER PRIMARY KEY,
  tweet_id        TEXT NOT NULL REFERENCES tweets(id),
  raw_token       TEXT NOT NULL,     -- as written in the tweet
  subject         TEXT,              -- human-readable asset name, set even when
                                     -- no price feed exists (e.g. 'YT-BulkSOL')
  resolved_symbol TEXT,              -- NULL = no chartable symbol
  asset_class     TEXT,              -- crypto | us_equity | commodity_fx | in_equity
  method          TEXT NOT NULL,     -- cashtag | llm | vision | alias
  source_field    TEXT NOT NULL,     -- text | quoted_text | image
  confidence      REAL
);

CREATE TABLE snapshots (
  id            INTEGER PRIMARY KEY,
  mention_id    INTEGER NOT NULL REFERENCES mentions(id),
  symbol        TEXT NOT NULL,
  asof_date     TEXT NOT NULL,
  close         REAL NOT NULL,
  st_value      REAL NOT NULL,
  st_direction  TEXT NOT NULL,
  cpr_pivot     REAL NOT NULL,
  cpr_tc        REAL NOT NULL,
  cpr_bc        REAL NOT NULL,
  prior_high    REAL NOT NULL,
  prior_low     REAL NOT NULL,
  cpr_width     REAL NOT NULL,
  narrow_cpr    INTEGER NOT NULL,
  verdict       TEXT NOT NULL,
  conflict      INTEGER NOT NULL,
  UNIQUE (mention_id, asof_date)
);

CREATE TABLE outcomes (
  snapshot_id   INTEGER NOT NULL REFERENCES snapshots(id),
  horizon_days  INTEGER NOT NULL,    -- 7, 30, 90
  fwd_return    REAL NOT NULL,
  evaluated_at  TEXT NOT NULL,
  PRIMARY KEY (snapshot_id, horizon_days)
);
```

### 9.1 Card types

Render selects one of three per mention, in this order:

| Condition | Card | Contents |
|---|---|---|
| `resolved_symbol` set and price fetch succeeded | **Chart card** | Tweet, 1D chart with both overlays, verdict, badges |
| `resolved_symbol` NULL but `subject` set | **No-chart card** | Tweet and subject, no indicators, no verdict. Q4 — this is where most `@DidiTrading` posts land |
| Neither set | **Unresolved entry** | Raw token and source tweet, in the bucket at the foot of the page |

`subject` is what separates "we know what Didi is talking about but no market
exists" from "we could not read this post at all." Collapsing the two would hide
extraction failures behind unchartable assets, and those need different fixes.

`outcomes` is what turns the feed into a **source scoreboard** — which accounts
are actually right, and whether the indicators beat the accounts. It is nearly
free to populate given `snapshots` exists, and expensive to reconstruct later
because the entry price at time-of-post is unrecoverable after the fact. Written
from day one; the reporting view can come much later.

## 10. Error handling

The governing rule: **a failed run must never look like a quiet news day.**

| Failure | Behaviour |
|---|---|
| X auth expired (`not_authenticated`) | Abort run, Telegram alert naming the error, no page rewrite |
| X List fetch fails | Same — abort loudly |
| Zero tweets returned, auth OK | Page renders "no posts in 24h", explicitly distinguished from a failure |
| Price fetch fails for one symbol | That card renders in an error state; all other cards proceed |
| Haiku extraction fails | Fall back to cashtag-only, banner on the page noting reduced recall |
| Symbol unresolved | Unresolved bucket, visible, with the raw token and source tweet |
| Telegram send fails | Log, page still written; not fatal |

Cookies expire on a scale of weeks. Auth failure is the expected steady-state
error, not an edge case, so it gets the loudest path.

## 11. Testing

**Primary golden fixture — `BINANCE:BTCUSDT`, 1D, captured 2026-08-06 07:58
UTC-4.** Binance data is what TradingView charts for this symbol, so any
mismatch is our bug rather than a data-source basis. Tolerance 0.01%.

Binance July 2026 bars: **H 66,956.15, L 57,800.19, C 62,887.88.**

| Field | Expected | Engine |
|---|---|---|
| Supertrend(22,3) | 60,426.28, **bullish** | 0.00001% |
| CPR pivot | 62,548.07 | 0.00001% |
| CPR BC | 62,378.17 | exact |
| CPR TC | 62,717.98 | 0.00001% |
| R1 | 67,295.96 | exact |
| S1 | 58,140.00 | 0.00001% |
| cprWidth | 0.5433% | ✓ |
| Inverted CPR | **no** — `bc < pivot < tc` | ✓ |
| Session candle | O 64,665.24 H 64,999.00 L 64,439.34 C 64,622.00 | |
| CPR position | above — `close > cprTop 62,717.98` | ✓ |
| Verdict | **Strong bullish**, narrow-CPR badge | ✓ |

Verified end-to-end against live Binance data on 2026-08-06.

**Secondary fixture — gold, TVC CFD. This is the inverted case**, and the §8
band-edge rule exists because of it. Prior-month OHLC is back-solved from the
plotted R1/S1: **H 5,419.319, L 4,098.741, C 4,671.793.** Tolerance is looser
here and Q2 governs whether it is used at all:

| Field | Expected |
|---|---|
| Supertrend(22,3) | 4,849.832, bearish |
| CPR pivot | 4,729.951 |
| CPR BC | 4,759.031 |
| CPR TC | 4,700.872 |
| R1 | 5,361.161 |
| S1 | 4,040.583 |
| cprWidth | 1.2296% |
| Inverted CPR | **yes** — `tc < pivot < bc` |
| Session candle | O 4,685.590 H 4,701.280 L 4,554.967 C 4,596.440 |
| CPR position | below — `close 4,596.440 < cprBottom 4,700.872` (the bottom edge is **TC** here) |
| Expected verdict | **Strong bearish** |

**Unit tests.**
- Supertrend against a hand-computed 30-bar fixture, verifying RMA-based ATR and
  the band-carry rules.
- Both CPR identities from §7.2, asserted on inverted and non-inverted months.
- Month-boundary stepping: levels must be constant within a month and change
  only on the 1st.
- Verdict grid — all six cells, plus both boundary conditions
  (`close == cprTop`, `close == cprBottom`), each tested in **both** the
  inverted and non-inverted orientation. Twelve cases, not six.

**Extraction tests.** A fixture set of real tweets from the §3.1 accounts,
including deliberate traps:

- `$GOLD` (Barrick Gold, US equity) versus "gold" (commodity).
- `$SOL` versus Solana spelled out.
- A tweet with no asset at all.
- **The Yuvraj case** — `🤝🤝` quote-tweeting text that names SBI. Text-only
  extraction must return nothing; text-plus-quoted must return `SBIN.NS`.
- **The IncomeSharks case** — one line plus a chart image. Vision must read the
  symbol from the chart header, and the result must carry
  `source_field = 'image'`.
- **The Didi case** — a farm token with no listed market. Must produce a
  no-chart card with `subject` set, **not** an unresolved entry and **not** a
  wrong resolution to a similarly named listed token.

That last trap is the dangerous one: a fuzzy matcher resolving "BulkSOL" to
`SOL` would produce a confident, wrong chart with a verdict attached.

## 12. Build phases

| Phase | Work | Verify |
|---|---|---|
| **0** | **DONE 2026-08-06.** Auth working, List `<list-id>` live, 60-tweet baseline captured (§3.1.1) | Verified |
| **1** | **DONE.** `ingest.py` + schema + retweet filtering | 24h of posts land in SQLite, deduplicated; no unapproved handle appears as an approving account; Ansem's retweets are excluded and everyone else's are kept |
| **2** | **DONE.** `extract.py` + `aliases.yaml`; cashtag, keyword, prose, quoted-text and image-vision passes | All §11 traps pass. The `🤝🤝` post yields nothing from text and `SBIN.NS` from quoted text, as specified |
| **3** | **DONE** (Q2 still open). `prices.py` + `indicators.py` | BTCUSDT golden fixture matches to **0.00001%** against live Binance data; both orientations tested |
| **4** | **DONE.** `verdict.py`, `chart.py`, `chart_png.py`, `render.py`, `telegram.py`, `run.py` | Real day: 23 posts, 54 charted, 21 unresolved, 0 LLM failures. Telegram digest + PNG covered by mocked tests |
| **5** | **DONE.** `run-daily.sh` (manual) + `install-cron.sh` → launchd at 07:00 | Scheduled run verified end-to-end: `exit: 0`, 54 charted, 54 snapshots |
| **5a** | **DONE.** Keychain from a non-interactive context | The launchd run fetched 200 tweets — Chrome cookie decryption works unattended. No token fallback needed |
| **5a** | **launchd Keychain check** — verify cookie decryption works from a scheduled context, not just an interactive shell | A cron-triggered `twitter whoami` returns `@<his-x-handle>`. If denied, fall back to explicit `TWITTER_AUTH_TOKEN`/`TWITTER_CT0` in a `chmod 600` env file — and only then |
| **6** | **DONE.** `outcomes.py` + scoreboard section | 57 snapshots persisted; scoring correct at 7/30/90d, immature horizons deferred. Real hit rates need ~30 days of history |

Phase 3 is the technical core. Phases 0–2 are unblocked today.

## 12.1 Implementation deviations (2026-08-06)

Three departures from the approved design, all deliberate.

**1. Charts are server-rendered inline SVG, not Lightweight Charts + a PNG
renderer.** §5 chose approach C for the page and B for Telegram. One SVG renderer
(`src/chart.py`) feeds both instead: no JS dependency, no headless browser for
the PNG path, one code path to test. Cost: the chart is static — no zoom or pan.
Reversible; the card layout does not depend on which renderer fills the slot.

**2. A deterministic keyword pass was added** (`extract.extract_keywords`,
recorded as `method = 'alias'`, already in the §9 enum). §10 specified that a
missing API key falls back to cashtag-only. Measured on the real feed, that path
found assets in **2 of 21 posts** — this list writes "the corrections in gold and
silver are over", not "$GC=F". Adding a registry-key scan over bare prose took it
to **10 charted plus 1 unchartable** with no API key at all.

It cannot invent a symbol; it only matches keys already in `aliases.yaml`.
Ambiguous keys (`coin`, `meta`, `link`, `oil`, …) are held back in
`keyword_exclude` and still resolve via cashtag or the LLM, which see context.

**3. Telegram uses a second, Pillow-based PNG renderer** (`chart_png.py`).
Deviation 1 claimed one renderer would serve both surfaces; that was wrong.
Telegram cannot display inline SVG, and every SVG→PNG converter needs `libcairo`,
a Homebrew system dependency. Pillow needs none. Both renderers consume the same
computed indicator values, so they cannot disagree about numbers — only pixels.

**4. The default LLM backend is `claude -p`, not the Anthropic SDK.** §6 assumed
metered API calls. Claude Code headless mode authenticates against the Max
subscription instead, so **no API key exists anywhere on disk** and the marginal
cost of a run is zero. `backend: api` remains available in `config/settings.yaml`
for anyone who wants the faster path.

Measured on the real feed, 35 tweets: **6m46s, zero call failures.** Roughly 12s
per text call and 17s per image, and a 4-worker pool produced **no measurable
speedup** — the CLI appears to serialise, so treat the run time as linear in
tweet count. Fine for a daily cron; it would not survive an hourly one.

Injection containment is unchanged by the backend choice: tweet text and chart
images are untrusted, but both paths can only return a token that must then match
a key already in `aliases.yaml`.

## 12.2 Findings from the first live runs

**Retries are mandatory under concurrency.** With a 4-worker pool, 18 of 22 CLI
calls failed in one run while the identical calls succeeded one at a time.
Transient, not deterministic. `_cli_call` now retries three times with backoff;
the next run was 0 failures out of 23.

**Binance is not sufficient for crypto.** `HYPE/USDT` exists there only as a
perpetual, not spot. `prices.fetch_crypto` now falls back binance → bybit → okx
and reports every venue it tried when all miss.

**Exact-key resolution was losing assets already in the registry.** The LLM
returns `HDFC Bank` and `Dr. Reddy's Laboratories`; the keys were `hdfcbank` and
`drreddy`. A punctuation-stripped index fixes it. This is *not* fuzzy matching —
`Bitcoinn` and `SOLANAA` still resolve to nothing, and `BulkSOL` still refuses to
become SOL. Normalised hits are recorded at confidence 0.9 to stay distinguishable.

**The unresolved bucket paid for itself immediately.** The first full LLM run
surfaced 50 unresolved tokens, most of them real NSE names Yuvraj posts about —
L&T, Siemens India, ABB, CG Power, Polycab, Thermax, CDSL, Apollo Hospitals,
Divi's, Dr. Reddy's, Max Healthcare — plus GME, Broadcom, RKLB, BONK, SUSHI.
Adding them took the day from **23 charted / 50 unresolved to 54 / 21**. This is
the intended maintenance loop: the bucket is a work queue, not a failure log.

## 12.3 The project lives in a TCC-protected folder

`~/Desktop`, `~/Documents` and `~/Downloads` are protected by macOS TCC.
Unattended launchd agents cannot read them without Full Disk Access. The failure
is deeply misleading — `ls` succeeds because metadata is not protected, while
reading the same file fails:

```
-rwxr-xr-x@ 1 tanmayshah staff 1550 run-daily.sh     <- ls works
cat: .../run-daily.sh: Operation not permitted        <- read blocked
```

launchd surfaces this as `/bin/zsh: can't open input file: …/run-daily.sh`,
which reads like a missing file rather than a permission denial.

The existing `com.tanmay.jobbot.*` agents avoid it by living at `~/jobbot`,
outside any protected folder. **Tanmay chose to keep this project on the Desktop
and grant Full Disk Access instead**, so `install-cron.sh` refuses by default and
installs under `--force`.

**FDA alone was not sufficient, and the reason is non-obvious.** With Full Disk
Access granted to `/usr/bin/caffeinate`, these all worked:

- `caffeinate → cat <Desktop file>`
- `caffeinate → zsh -c 'cd <Desktop project> && uv run …'`
- `caffeinate → /tmp/hop.sh → uv run …` (a hop, but from an unprotected script)

While this consistently failed with
`failed to open pyproject.toml: Operation not permitted`:

- `caffeinate → <Desktop>/run-daily.sh → uv run …`

**Executing a script that itself resides in the protected folder is what breaks
the chain**, regardless of `exec`, `WorkingDirectory`, or absolute paths. The
grant follows the process, and exec'ing a protected-path script drops it.

Fix: `install-cron.sh` generates `~/.local/bin/xsignal-run.sh`, outside any
protected folder, and **inlines** the run rather than calling `run-daily.sh`.
Calling the Desktop copy from the launcher fails for exactly the same reason.
`run-daily.sh` stays as the manual entry point; the launcher is its scheduled
twin, and edits must be made in both.

Two consequences to remember. Granting FDA to `/usr/bin/caffeinate` gives that
binary access to every protected folder on the machine, not just this one. And
the grant is per-binary: a future change to `ProgramArguments[0]` silently
re-breaks the schedule, with the same misleading error.

A second, independent permission still has to clear on the first real run:
Keychain access for Chrome's cookie store (Phase 5a). FDA and Keychain are
separate gates, and passing one says nothing about the other.

## 13. Risks

**X cookie reads are unofficial.** One list call per day, read-only, from a
residential IP is low risk — but not zero, and his X handle is tied to his real
account. `following`/`followers` are the endpoints the reference warns about at
frequency; the design calls neither. Seeding is by named handles, so the risky
class of call never runs at all.

**Cookies are read live from Chrome, not stored.** No token file exists, so
there is nothing to leak and nothing to rotate. Re-login in Chrome is the whole
refresh procedure. Trade-off: the job depends on Chrome's profile staying put,
and on Keychain decryption being permitted in whatever context the cron job runs
— see the launchd note in §12, Phase 5.

**yfinance is unofficial and breaks periodically.** Polygon (~$29/mo) is the
paid escape hatch for US symbols. Indian equities have no equally clean paid
fallback, and `@YuvrajShah02` guarantees NSE tickers will appear (§3.1), so NSE
coverage must be verified in Phase 3 rather than assumed.

**Extraction misses are the dominant recall risk, not resolution.** Q3 shows two
of five accounts routinely placing the call outside the tweet text. A text-only
v1 will underperform in a way that looks like a quiet feed rather than a bug —
which is the same failure mode §10 exists to prevent, arriving through a
different door.

**Extraction is the accuracy ceiling.** A ticker missed is a card that never
appears, and silence is indistinguishable from no-signal. The unresolved bucket
exists so that misses are visible rather than invisible.

**Mechanical verdicts invite over-trust.** Two indicators on one timeframe is a
narrow lens. The page should read as an input, not a recommendation.

## 14. Sign-off

Approved by: Tanmay Shah, 2026-08-06.

Approved with Q2 (gold symbol) deliberately left open, to be resolved in Phase 3
against live data rather than decided in advance.
