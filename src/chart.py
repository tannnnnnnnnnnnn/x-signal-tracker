"""Inline SVG candlestick charts with Supertrend and SwingCPR overlays.

Server-side SVG rather than the spec's Lightweight Charts + PNG pair: one
renderer feeds both the page and Telegram, with no JS and no headless browser.
Trade-off is a static (non-zoomable) chart.
"""

from __future__ import annotations

from html import escape

import pandas as pd

from indicators import CPR, Supertrend

W, H = 760, 300
PAD_L, PAD_R, PAD_T, PAD_B = 8, 78, 10, 22

COLORS = {
    "up": "#26a69a",
    "down": "#ef5350",
    "st_bull": "#26a69a",
    "st_bear": "#ef5350",
    "pivot": "#f5a623",
    "tc": "#4a90d9",
    "bc": "#4a90d9",
    "r1": "#ef5350",
    "s1": "#26a69a",
    "grid": "#2a2e39",
    "text": "#9aa0aa",
}


def _scale(lo: float, hi: float):
    span = (hi - lo) or 1.0
    lo, hi = lo - span * 0.06, hi + span * 0.06
    span = hi - lo

    def y(v: float) -> float:
        return PAD_T + (hi - v) / span * (H - PAD_T - PAD_B)

    return y


def render_svg(df: pd.DataFrame, st: Supertrend, cpr: CPR, bars: int = 120) -> str:
    """Candles plus both indicators. `df` must be daily OHLC ascending by date."""
    d = df.tail(bars)
    stl = st.series.reindex(d.index)

    levels = [
        ("pivot", cpr.pivot), ("tc", cpr.tc), ("bc", cpr.bc),
        ("r1", cpr.r1), ("s1", cpr.s1),
    ]
    lo = min(d["low"].min(), stl["supertrend"].min(), min(v for _, v in levels))
    hi = max(d["high"].max(), stl["supertrend"].max(), max(v for _, v in levels))
    y = _scale(float(lo), float(hi))

    plot_w = W - PAD_L - PAD_R
    step = plot_w / max(len(d), 1)
    body = max(1.4, step * 0.6)

    parts = [
        f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" '
        f'style="width:100%;height:auto;display:block">',
        f'<rect width="{W}" height="{H}" fill="none"/>',
    ]

    # CPR levels and the price axis labels for them.
    for name, value in levels:
        yy = y(value)
        dash = "" if name == "pivot" else ' stroke-dasharray="3 3"'
        parts.append(
            f'<line x1="{PAD_L}" y1="{yy:.1f}" x2="{PAD_L + plot_w:.1f}" y2="{yy:.1f}" '
            f'stroke="{COLORS[name]}" stroke-width="1" opacity="0.75"{dash}/>'
        )
        parts.append(
            f'<text x="{PAD_L + plot_w + 4:.1f}" y="{yy + 3.5:.1f}" fill="{COLORS[name]}" '
            f'font-size="10" font-family="ui-monospace,monospace">'
            f'{name.upper()} {value:,.2f}</text>'
        )

    # Candles.
    for i, (_, row) in enumerate(d.iterrows()):
        cx = PAD_L + i * step + step / 2
        up = row["close"] >= row["open"]
        col = COLORS["up"] if up else COLORS["down"]
        parts.append(
            f'<line x1="{cx:.1f}" y1="{y(row["high"]):.1f}" x2="{cx:.1f}" '
            f'y2="{y(row["low"]):.1f}" stroke="{col}" stroke-width="1"/>'
        )
        top, bot = y(max(row["open"], row["close"])), y(min(row["open"], row["close"]))
        parts.append(
            f'<rect x="{cx - body / 2:.1f}" y="{top:.1f}" width="{body:.1f}" '
            f'height="{max(bot - top, 1):.1f}" fill="{col}"/>'
        )

    # Supertrend, split at each direction flip so the colour changes cleanly.
    segment: list[str] = []
    prev_dir = None
    for i, (idx, row) in enumerate(stl.iterrows()):
        value, direction = row["supertrend"], row["direction"]
        if pd.isna(value):
            continue
        cx = PAD_L + i * step + step / 2
        if direction != prev_dir and segment:
            key = "st_bull" if prev_dir == "bull" else "st_bear"
            parts.append(
                f'<polyline points="{" ".join(segment)}" fill="none" '
                f'stroke="{COLORS[key]}" stroke-width="1.6"/>'
            )
            segment = []
        segment.append(f"{cx:.1f},{y(value):.1f}")
        prev_dir = direction
    if segment:
        key = "st_bull" if prev_dir == "bull" else "st_bear"
        parts.append(
            f'<polyline points="{" ".join(segment)}" fill="none" '
            f'stroke="{COLORS[key]}" stroke-width="1.6"/>'
        )

    first, last = d.index[0].strftime("%d %b %y"), d.index[-1].strftime("%d %b %y")
    parts.append(
        f'<text x="{PAD_L}" y="{H - 6}" fill="{COLORS["text"]}" font-size="10" '
        f'font-family="ui-monospace,monospace">{escape(first)}</text>'
    )
    parts.append(
        f'<text x="{PAD_L + plot_w:.1f}" y="{H - 6}" fill="{COLORS["text"]}" font-size="10" '
        f'text-anchor="end" font-family="ui-monospace,monospace">{escape(last)}</text>'
    )
    parts.append("</svg>")
    return "".join(parts)
