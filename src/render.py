"""Page rendering, per spec §9.1 — three card types."""

from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "out" / "dist.html"

VERDICT_CLASS = {
    "Strong bullish": "vg", "Bullish, indecisive": "vg-soft",
    "Strong bearish": "vr", "Bearish, indecisive": "vr-soft",
    "Conflict": "vy",
}

CSS = """
:root{--bg:#0f1115;--card:#171a21;--line:#242832;--tx:#e6e8ec;--dim:#8b919c;
--g:#26a69a;--r:#ef5350;--y:#f5a623;--b:#4a90d9}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);
font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
.wrap{max-width:860px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:20px;margin:0 0 4px}
.sub{color:var(--dim);font-size:13px;margin-bottom:20px}
.banner{background:#3a2a12;border:1px solid #6b4a1a;border-radius:8px;
padding:10px 12px;margin-bottom:16px;font-size:13px}
.banner.err{background:#3a1618;border-color:#7a2a2e}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:14px 16px;margin-bottom:14px}
.hd{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap;margin-bottom:6px}
.who{font-weight:600}
.rt{color:var(--dim);font-size:12px}
.when{color:var(--dim);font-size:12px;margin-left:auto}
.tw{color:#c9ced6;white-space:pre-wrap;margin:6px 0 12px;font-size:13px}
.quo{border-left:2px solid var(--line);padding-left:10px;color:var(--dim);
margin:6px 0 12px;font-size:13px;white-space:pre-wrap}
.sym{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;margin-bottom:8px}
.tick{font:600 15px ui-monospace,monospace}
.px{color:var(--dim);font:12px ui-monospace,monospace}
.v{padding:3px 9px;border-radius:99px;font-size:12px;font-weight:600}
.vg{background:rgba(38,166,154,.16);color:var(--g)}
.vg-soft{background:rgba(38,166,154,.09);color:var(--g)}
.vr{background:rgba(239,83,80,.16);color:var(--r)}
.vr-soft{background:rgba(239,83,80,.09);color:var(--r)}
.vy{background:rgba(245,166,35,.16);color:var(--y)}
.badge{background:#22262f;color:var(--dim);padding:3px 8px;border-radius:99px;font-size:11px}
.clash{background:rgba(245,166,35,.12);border:1px solid rgba(245,166,35,.35);
color:#f0b757;border-radius:8px;padding:8px 10px;margin:10px 0 0;font-size:12.5px}
.meta{display:flex;gap:14px;flex-wrap:wrap;color:var(--dim);
font:11.5px ui-monospace,monospace;margin-top:10px}
a{color:var(--b);text-decoration:none}
a:hover{text-decoration:underline}
.sec{margin:28px 0 12px;font-size:13px;color:var(--dim);text-transform:uppercase;
letter-spacing:.06em}
.unres{background:var(--card);border:1px dashed var(--line);border-radius:8px;
padding:10px 12px;margin-bottom:8px;font-size:13px;color:var(--dim)}
.empty{color:var(--dim);padding:32px 0;text-align:center}
table.sb{width:100%;border-collapse:collapse;font-size:13px}
table.sb th{text-align:left;color:var(--dim);font-weight:500;
border-bottom:1px solid var(--line);padding:6px 8px 8px}
table.sb td{padding:7px 8px;border-bottom:1px solid var(--line);
font-family:ui-monospace,monospace}
table.sb tr:last-child td{border-bottom:none}
.pos{color:var(--g)}
.neg{color:var(--r)}
"""


def _fmt(v: float) -> str:
    return f"{v:,.2f}" if abs(v) >= 1 else f"{v:,.6f}"


def _card_chart(c: dict) -> str:
    v = c["verdict"]
    badges = "".join(f'<span class="badge">{escape(b)}</span>' for b in v["badges"])
    clash = (
        f'<div class="clash"><strong>Source disagreement.</strong> '
        f'@{escape(c["handle"])} reads {escape(c["sentiment"])}; '
        f'your indicators say {escape(v["verdict"]).lower()}.</div>'
        if c.get("disagrees") else ""
    )
    return f"""<div class="card">
{_header(c)}
{_body(c)}
<div class="sym">
  <span class="tick">{escape(c["symbol"])}</span>
  <span class="px">{escape(c["name"])} &middot; {_fmt(c["close"])}</span>
  <span class="v {VERDICT_CLASS.get(v["verdict"], "vy")}">{escape(v["verdict"])}</span>
  {badges}
</div>
{c["svg"]}
<div class="meta">
  <span>ST {_fmt(c["st_value"])} ({escape(v["st_direction"])})</span>
  <span>P {_fmt(c["cpr"]["pivot"])}</span>
  <span>BC {_fmt(c["cpr"]["bc"])}</span>
  <span>TC {_fmt(c["cpr"]["tc"])}</span>
  <span>R1 {_fmt(c["cpr"]["r1"])}</span>
  <span>S1 {_fmt(c["cpr"]["s1"])}</span>
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

    html = [f'<div class="wrap"><h1>X Signal Tracker</h1>',
            f'<div class="sub">{escape(now)} &middot; '
            f'{stats["kept"]} posts &middot; {len(chart_cards)} charted &middot; '
            f'{len(nochart_cards)} unchartable &middot; {len(unresolved)} unresolved</div>',
            banners]

    if not cards and not unresolved:
        html.append('<div class="empty">No assets mentioned in the last 24 hours.</div>')

    if chart_cards:
        html.append('<div class="sec">Charted</div>')
        html.extend(_card_chart(c) for c in chart_cards)

    if nochart_cards:
        html.append('<div class="sec">Mentioned &mdash; no price feed</div>')
        html.extend(_card_nochart(c) for c in nochart_cards)

    if unresolved:
        html.append('<div class="sec">Unresolved</div>')
        for u in unresolved:
            html.append(
                f'<div class="unres"><strong>{escape(u["raw_token"])}</strong> '
                f'&mdash; @{escape(u["handle"])} &middot; '
                f'<a href="{escape(u["url"])}">open</a> '
                f'&middot; found by {escape(u["method"])} in {escape(u["source_field"])}</div>'
            )

    html.append(_scoreboard(board or []))
    html.append("</div>")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        f"<!doctype html><html><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>X Signal Tracker</title><style>{CSS}</style></head>"
        f"<body>{''.join(html)}</body></html>",
        encoding="utf-8",
    )
    return out
