"""Page rendering, per spec §9.1 — three card types.

Charts are TradingView Lightweight Charts (CDN), interactive: pan, zoom,
and a 4H/1D/1W timeframe switcher per card. Chart data ships as JSON blobs
inline; charts initialise lazily as cards scroll into view.
"""

from __future__ import annotations

import json
from datetime import datetime
from html import escape
from pathlib import Path

LWC_CDN = "https://unpkg.com/lightweight-charts@4.2.3/dist/lightweight-charts.standalone.production.js"

OUT = Path(__file__).resolve().parent.parent / "out" / "dist.html"

VERDICT_CLASS = {
    "Strong bullish": "vg", "Bullish, indecisive": "vg-soft",
    "Strong bearish": "vr", "Bearish, indecisive": "vr-soft",
    "Conflict": "vy",
}

CSS = """
:root{--bg:#0c0e13;--card:#151821;--well:#10131a;--line:#232837;--tx:#e8eaef;
--dim:#8f96a3;--g:#26a69a;--r:#ef5350;--y:#f5a623;--b:#5b9de0}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);
font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
-webkit-font-smoothing:antialiased}
.wrap{max-width:880px;margin:0 auto;padding:28px 18px 72px}
.top{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap}
h1{font-size:21px;margin:0;letter-spacing:-.01em}
.date{color:var(--dim);font-size:13px}
.stats{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0 24px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:99px;
padding:4px 12px;font-size:12px;color:var(--dim)}
.stat b{color:var(--tx);font-weight:600;margin-right:5px;font-family:ui-monospace,monospace}
.banner{background:#33250f;border:1px solid #6b4a1a;border-radius:10px;
padding:10px 14px;margin-bottom:12px;font-size:13px;color:#e8c68a}
.banner.err{background:#331416;border-color:#7a2a2e;color:#eba1a3}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:16px 18px;margin-bottom:16px;transition:border-color .15s}
.card:hover{border-color:#303748}
.hd{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap;margin-bottom:6px}
.who{font-weight:650}
.rt{color:var(--dim);font-size:12px}
.when{color:var(--dim);font-size:12px;margin-left:auto}
.tw{color:#c6cbd4;white-space:pre-wrap;margin:6px 0 14px;font-size:13px}
.quo{border-left:2px solid var(--line);padding-left:10px;color:var(--dim);
margin:6px 0 14px;font-size:13px;white-space:pre-wrap}
.sym{display:flex;gap:10px;align-items:center;flex-wrap:wrap;
background:var(--well);border:1px solid var(--line);border-radius:10px;
padding:9px 13px;margin-bottom:10px}
.tick{font:650 15px ui-monospace,monospace;letter-spacing:.01em}
.px{color:var(--dim);font:12px ui-monospace,monospace}
.v{display:inline-flex;align-items:center;gap:6px;margin-left:auto;
padding:3px 10px;border-radius:99px;font-size:12px;font-weight:600}
.v::before{content:'';width:6px;height:6px;border-radius:50%;background:currentColor}
.vg{background:rgba(38,166,154,.15);color:var(--g)}
.vg-soft{background:rgba(38,166,154,.08);color:var(--g)}
.vr{background:rgba(239,83,80,.15);color:var(--r)}
.vr-soft{background:rgba(239,83,80,.08);color:var(--r)}
.vy{background:rgba(245,166,35,.15);color:var(--y)}
.badge{background:#20242f;border:1px solid var(--line);color:var(--dim);
padding:2px 9px;border-radius:99px;font-size:11px}
.clash{background:rgba(245,166,35,.1);border:1px solid rgba(245,166,35,.3);
color:#f0b757;border-radius:10px;padding:9px 12px;margin:10px 0 0;font-size:12.5px}
.meta{display:flex;gap:16px;flex-wrap:wrap;color:var(--dim);
font:11.5px ui-monospace,monospace;margin-top:10px}
a{color:var(--b);text-decoration:none}
a:hover{text-decoration:underline}
.sec{display:flex;align-items:center;gap:10px;margin:30px 0 14px;font-size:12px;
color:var(--dim);text-transform:uppercase;letter-spacing:.08em;font-weight:600}
.sec b{background:var(--card);border:1px solid var(--line);border-radius:99px;
padding:1px 9px;font-size:11px;color:var(--tx)}
.sec::after{content:'';flex:1;height:1px;background:var(--line)}
details.fold>summary.sec{cursor:pointer;list-style:none;user-select:none}
details.fold>summary.sec::-webkit-details-marker{display:none}
details.fold>summary.sec::before{content:'\\25B8';font-size:10px;transition:transform .15s}
details.fold[open]>summary.sec::before{transform:rotate(90deg)}
.unres{background:var(--card);border:1px dashed var(--line);border-radius:10px;
padding:10px 13px;margin-bottom:8px;font-size:13px;color:var(--dim)}
.empty{color:var(--dim);padding:32px 0;text-align:center}
table.sb{width:100%;border-collapse:collapse;font-size:13px}
table.sb th{text-align:left;color:var(--dim);font-weight:500;
border-bottom:1px solid var(--line);padding:6px 8px 8px}
table.sb td{padding:7px 8px;border-bottom:1px solid var(--line);
font-family:ui-monospace,monospace}
table.sb tr:last-child td{border-bottom:none}
.pos{color:var(--g)}
.neg{color:var(--r)}
.tfbar{display:inline-flex;gap:2px;margin:2px 0 8px;background:var(--well);
border:1px solid var(--line);border-radius:8px;padding:3px}
.tfbar button{background:none;border:0;color:var(--dim);border-radius:6px;
padding:3px 12px;font:600 12px ui-monospace,monospace;cursor:pointer}
.tfbar button:hover{color:var(--tx)}
.tfbar button.on{background:rgba(91,157,224,.16);color:var(--b)}
.chart{height:340px;border:1px solid var(--line);border-radius:10px;overflow:hidden}
.chartwrap{position:relative}
.legend{position:absolute;top:8px;left:8px;z-index:3;
display:grid;grid-auto-flow:column;grid-template-rows:repeat(4,auto);
gap:1px 12px;font:10.5px ui-monospace,monospace;
background:rgba(12,14,19,.85);border:1px solid var(--line);
border-radius:8px;padding:5px 7px;backdrop-filter:blur(3px)}
.legend div{display:flex;align-items:center;gap:6px;white-space:nowrap;min-width:158px;
cursor:pointer;border-radius:5px;padding:1px 5px;user-select:none}
.legend div:hover{background:rgba(255,255,255,.06)}
.legend div.off{opacity:.35}
.legend i{width:14px;border-top:2px solid;flex:none}
.legend i.dot{border-top-style:dotted;border-top-width:3px}
.legend em{color:#c6cbd4;font-style:normal}
.legend b{color:var(--dim);font-weight:400;margin-left:auto;padding-left:8px}
@media(max-width:560px){.legend{grid-template-rows:repeat(8,auto)}
.legend div{min-width:0}.legend b{display:none}}
"""


JS = """
const inited = new Set();

function initChart(box) {
  const id = box.dataset.id;
  if (inited.has(id)) return;
  inited.add(id);
  const data = JSON.parse(document.getElementById('data-' + id).textContent);
  const el = box.querySelector('.chart');
  const chart = LightweightCharts.createChart(el, {
    autoSize: true,
    layout: {background: {color: '#10131a'}, textColor: '#8f96a3',
             fontFamily: 'ui-monospace, monospace', fontSize: 11},
    grid: {vertLines: {color: '#1c202a'}, horzLines: {color: '#1c202a'}},
    timeScale: {timeVisible: true, secondsVisible: false, borderColor: '#242832'},
    rightPriceScale: {borderColor: '#242832'},
  });
  const candles = chart.addCandlestickSeries({
    upColor: '#26a69a', downColor: '#ef5350', borderVisible: false,
    wickUpColor: '#26a69a', wickDownColor: '#ef5350',
  });
  const lineOpts = {priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false};
  const stBull = chart.addLineSeries({color: '#26a69a', lineWidth: 2, ...lineOpts});
  const stBear = chart.addLineSeries({color: '#ef5350', lineWidth: 2, ...lineOpts});
  // SwingCPR as dots, not solid lines — five solid levels plus Supertrend was
  // unreadable. [color, lineStyle, lineWidth, axis label]; lineStyle 4 = SparseDotted.
  // Green/red belong to the Supertrend alone: R1/S1 use pale tints so a dotted
  // level never reads as a trend fragment.
  const cprStyle = {pivot: ['#f5a623', 4, 2, 'P'], bc: ['#8b919c', 4, 1, 'BC'],
                    tc: ['#8b919c', 4, 1, 'TC'], r1: ['#7ec8a9', 4, 1, 'R1'],
                    s1: ['#e8908d', 4, 1, 'S1']};
  const ema50 = chart.addLineSeries({color: '#4a90d9', lineWidth: 1, ...lineOpts});
  const ema200 = chart.addLineSeries({color: '#c678dd', lineWidth: 1, ...lineOpts});
  const cprSeries = {};
  for (const k in cprStyle) {
    const [color, lineStyle, lineWidth, title] = cprStyle[k];
    // Named on the price axis as well as in the legend — the levels sit close
    // together, so a swatch alone does not say which dotted row is which.
    cprSeries[k] = chart.addLineSeries({color, lineStyle, lineWidth, title,
                                        ...lineOpts, lastValueVisible: true});
  }

  // Legend overlay. Each row: series key, label, swatch colour, dotted?
  const rows = [['st', 'Supertrend (22,3)', '#26a69a', false],
                ['ema50', 'EMA 50', '#4a90d9', false],
                ['ema200', 'EMA 200', '#c678dd', false],
                ['pivot', 'CPR pivot', '#f5a623', true],
                ['tc', 'CPR TC', '#8b919c', true],
                ['bc', 'CPR BC', '#8b919c', true],
                ['r1', 'CPR R1', '#7ec8a9', true],
                ['s1', 'CPR S1', '#e8908d', true]];
  // Rows toggle their series on click — the direct answer to "too many lines":
  // hide what you are not reading right now.
  const toggles = {st: [stBull, stBear], ema50: [ema50], ema200: [ema200]};
  for (const k in cprSeries) toggles[k] = [cprSeries[k]];
  const legend = box.querySelector('.legend');
  const cells = {};
  for (const [key, label, color, dotted] of rows) {
    const row = document.createElement('div');
    row.title = 'click to show/hide';
    row.innerHTML = '<i class="' + (dotted ? 'dot' : '') + '" style="border-color:' +
                    color + '"></i><em>' + label + '</em><b></b>';
    row.addEventListener('click', () => {
      const off = row.classList.toggle('off');
      for (const s of toggles[key]) s.applyOptions({visible: !off});
    });
    legend.appendChild(row);
    cells[key] = {swatch: row.querySelector('i'), value: row.querySelector('b')};
  }
  const fmt = v => v == null ? '—'
    : Math.abs(v) >= 1 ? v.toLocaleString(undefined, {maximumFractionDigits: 2})
                       : v.toFixed(6);
  // st/ema keys -> {at: Map(time -> point), last: point}, rebuilt per timeframe.
  // CPR levels are month-long steps instead, so they are looked up by segment.
  let series = {};
  let lastTime = null;
  const cprKeys = {pivot: 1, tc: 1, bc: 1, r1: 1, s1: 1};

  function cprAt(key, time) {
    const t = time == null ? lastTime : time;
    for (const seg of data.cpr) {
      if (t >= seg.start && t < seg.end) return {value: seg[key]};
    }
    const tail = data.cpr[data.cpr.length - 1];
    return tail ? {value: tail[key]} : null;
  }

  function updateLegend(time) {
    for (const [key] of rows) {
      const s = series[key];
      const p = cprKeys[key] ? cprAt(key, time)
              : !s ? null : (time == null ? s.last : s.at.get(time) || null);
      cells[key].value.textContent = p ? fmt(p.value) : '—';
      if (key === 'st') {
        cells.st.swatch.style.borderColor =
          p && p.dir === 'bear' ? '#ef5350' : '#26a69a';
      }
    }
  }
  chart.subscribeCrosshairMove(p => updateLegend(p.time == null ? null : p.time));

  function index(points) {
    const at = new Map();
    for (const p of points) at.set(p.time, p);
    return {at, last: points.length ? points[points.length - 1] : null};
  }

  function setTF(tf) {
    const d = data[tf];
    if (!d) return;
    candles.setData(d.candles);
    // Supertrend, coloured by direction: two series, whitespace points keep the
    // inactive direction's line broken instead of joining across flips.
    const bull = [], bear = [];
    for (const p of d.st) {
      (p.dir === 'bull' ? bull : bear).push({time: p.time, value: p.value});
      (p.dir === 'bull' ? bear : bull).push({time: p.time});
    }
    stBull.setData(bull);
    stBear.setData(bear);
    // Empty when the series is shorter than the EMA period (young tokens, 1W).
    ema50.setData(d.ema50 || []);
    ema200.setData(d.ema200 || []);
    // Monthly CPR: flat month-long steps, clipped to the candle range.
    const first = d.candles.length ? d.candles[0].time : 0;
    const last = d.candles.length ? d.candles[d.candles.length - 1].time : 0;
    for (const k in cprSeries) {
      const pts = [];
      for (const seg of data.cpr) {
        if (seg.end < first || seg.start > last) continue;
        const a = Math.max(seg.start, first);
        const b = Math.min(seg.end, last);
        if (b - 60 <= a) continue;
        pts.push({time: a, value: seg[k]}, {time: b - 60, value: seg[k]}, {time: b - 30});
      }
      pts.pop();
      cprSeries[k].setData(pts);
    }
    series = {st: index(d.st), ema50: index(d.ema50 || []), ema200: index(d.ema200 || [])};
    lastTime = last;
    updateLegend(null);
    const n = d.candles.length;
    chart.timeScale().setVisibleLogicalRange({from: Math.max(0, n - 130), to: n + 3});
    box.querySelectorAll('.tfbar button').forEach(b =>
      b.classList.toggle('on', b.dataset.tf === tf));
  }

  box.querySelectorAll('.tfbar button').forEach(b =>
    b.addEventListener('click', () => setTF(b.dataset.tf)));
  setTF('1d');
}

const io = new IntersectionObserver(entries => {
  for (const e of entries) {
    if (e.isIntersecting) { initChart(e.target); io.unobserve(e.target); }
  }
}, {rootMargin: '300px'});
document.querySelectorAll('.chartbox').forEach(b => io.observe(b));
"""

TF_LABELS = {"4h": "4H", "1d": "1D", "1w": "1W"}


def _fmt(v: float) -> str:
    return f"{v:,.2f}" if abs(v) >= 1 else f"{v:,.6f}"


def _card_chart(c: dict, idx: int) -> str:
    v = c["verdict"]
    badges = "".join(f'<span class="badge">{escape(b)}</span>' for b in v["badges"])
    clash = (
        f'<div class="clash"><strong>Source disagreement.</strong> '
        f'@{escape(c["handle"])} reads {escape(c["sentiment"])}; '
        f'your indicators say {escape(v["verdict"]).lower()}.</div>'
        if c.get("disagrees") else ""
    )
    tfs = [tf for tf in ("4h", "1d", "1w") if tf in c["chart_data"]]
    buttons = "".join(
        f'<button data-tf="{tf}">{TF_LABELS[tf]}</button>' for tf in tfs
    )
    # </script> inside a JSON string would end the block early; escape the slash.
    payload = json.dumps(c["chart_data"], separators=(",", ":")).replace("</", "<\\/")
    return f"""<div class="card">
{_header(c)}
{_body(c)}
<div class="sym">
  <span class="tick">{escape(c["symbol"])}</span>
  <span class="px">{escape(c["name"])} &middot; {_fmt(c["close"])}</span>
  {badges}
  <span class="v {VERDICT_CLASS.get(v["verdict"], "vy")}">{escape(v["verdict"])}</span>
</div>
<div class="chartbox" data-id="{idx}">
  <div class="tfbar">{buttons}</div>
  <div class="chartwrap">
    <div class="chart"></div>
    <div class="legend"></div>
  </div>
</div>
<script type="application/json" id="data-{idx}">{payload}</script>
<div class="meta">
  <span>ST {_fmt(c["st_value"])} ({escape(v["st_direction"])})</span>
  <span>CPR {escape(c["cpr"]["period"])} &middot; {c["cpr"]["width"] * 100:.2f}% wide</span>
</div>
{clash}
</div>"""


def _card_nochart(c: dict) -> str:
    return f"""<div class="card">
{_header(c)}
{_body(c)}
<div class="sym">
  <span class="tick">{escape(c["subject"])}</span>
  <span class="badge">no price feed &mdash; not charted</span>
</div>
</div>"""


def _header(c: dict) -> str:
    rt = f'<span class="rt">retweeted @{escape(c["author_handle"])}</span>' if c["is_retweet"] else ""
    return (
        f'<div class="hd"><span class="who">@{escape(c["handle"])}</span>{rt}'
        f'<span class="when">{escape(c["when"])} &middot; '
        f'<a href="{escape(c["url"])}">open</a></span></div>'
    )


def _body(c: dict) -> str:
    out = f'<div class="tw">{escape(c["text"])}</div>' if c["text"].strip() else ""
    if c.get("quoted_text"):
        out += f'<div class="quo">{escape(c["quoted_text"])}</div>'
    return out


def _scoreboard(board: list[dict]) -> str:
    """Per-account 30-day hit rate. Conflict verdicts are excluded upstream —
    they make no directional claim, so scoring them would be dishonest."""
    if not board:
        return (
            '<div class="sec">Source scoreboard</div>'
            '<div class="unres">No scored calls yet. Snapshots are recorded daily; '
            'the first 30-day outcomes land a month after the first run.</div>'
        )
    rows = "".join(
        f'<tr><td>@{escape(b["handle"])}</td><td>{b["n"]}</td>'
        f'<td>{b["hit_rate"] * 100:.0f}%</td>'
        f'<td class="{"pos" if b["avg_return"] >= 0 else "neg"}">'
        f'{b["avg_return"] * 100:+.1f}%</td></tr>'
        for b in board
    )
    return (
        '<div class="sec">Source scoreboard &mdash; 30 day</div>'
        '<div class="card"><table class="sb">'
        '<tr><th>Account</th><th>Calls</th><th>Hit rate</th><th>Avg return</th></tr>'
        f'{rows}</table></div>'
    )


def render(cards: list[dict], unresolved: list[dict], stats: dict,
           warnings: list[str], errors: list[str], out: Path = OUT,
           board: list[dict] | None = None) -> Path:
    now = datetime.now().strftime("%a %d %b %Y, %H:%M")

    banners = "".join(f'<div class="banner err">{escape(e)}</div>' for e in errors)
    banners += "".join(f'<div class="banner">{escape(w)}</div>' for w in warnings)

    chart_cards = [c for c in cards if c["kind"] == "chart"]
    nochart_cards = [c for c in cards if c["kind"] == "nochart"]

    html = [f'<div class="wrap"><div class="top"><h1>X Signal Tracker</h1>'
            f'<span class="date">{escape(now)}</span></div>',
            f'<div class="stats">'
            f'<span class="stat"><b>{stats["kept"]}</b>posts</span>'
            f'<span class="stat"><b>{len(chart_cards)}</b>charted</span>'
            f'<span class="stat"><b>{len(nochart_cards)}</b>unchartable</span>'
            f'<span class="stat"><b>{len(unresolved)}</b>unresolved</span></div>',
            banners]

    if not cards and not unresolved:
        html.append('<div class="empty">No assets mentioned in the last 24 hours.</div>')

    if chart_cards:
        html.append(f'<div class="sec">Charted <b>{len(chart_cards)}</b></div>')
        html.extend(_card_chart(c, i) for i, c in enumerate(chart_cards))

    if nochart_cards:
        html.append(f'<div class="sec">Mentioned &mdash; no price feed <b>{len(nochart_cards)}</b></div>')
        html.extend(_card_nochart(c) for c in nochart_cards)

    if unresolved:
        # Folded by default: mostly noise (usernames, half-tickers), but kept
        # inspectable — spec §10, nothing silently dropped.
        html.append(f'<details class="fold"><summary class="sec">Unresolved '
                    f'<b>{len(unresolved)}</b></summary>')
        for u in unresolved:
            html.append(
                f'<div class="unres"><strong>{escape(u["raw_token"])}</strong> '
                f'&mdash; @{escape(u["handle"])} &middot; '
                f'<a href="{escape(u["url"])}">open</a> '
                f'&middot; found by {escape(u["method"])} in {escape(u["source_field"])}</div>'
            )
        html.append('</details>')

    html.append(_scoreboard(board or []))
    html.append("</div>")

    scripts = ""
    if chart_cards:
        scripts = f'<script src="{LWC_CDN}"></script><script>{JS}</script>'

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        f"<!doctype html><html><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>X Signal Tracker</title><style>{CSS}</style></head>"
        f"<body>{''.join(html)}{scripts}</body></html>",
        encoding="utf-8",
    )
    return out
