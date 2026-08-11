"""PNG candlesticks for Telegram, drawn with Pillow.

A second renderer alongside chart.py's SVG, which the deviation note in §12.1
tried to avoid. It exists because Telegram cannot display inline SVG and the
SVG->PNG converters all need libcairo, a Homebrew system dependency. Pillow has
none. Both renderers consume the same computed indicator values, so they cannot
disagree about the numbers -- only about pixels.
"""

from __future__ import annotations

import io

import pandas as pd
from PIL import Image, ImageDraw

from indicators import CPR, Supertrend

W, H = 900, 420
PAD_L, PAD_R, PAD_T, PAD_B = 12, 110, 34, 26

BG = (15, 17, 21)
UP = (38, 166, 154)
DOWN = (239, 83, 80)
DIM = (139, 145, 156)
LEVELS = {
    "P": (245, 166, 35), "BC": (74, 144, 217), "TC": (74, 144, 217),
    "R1": (239, 83, 80), "S1": (38, 166, 154),
}


def render_png(df: pd.DataFrame, st: Supertrend, cpr: CPR, title: str,
               verdict: str, bars: int = 120) -> bytes:
    d = df.tail(bars)
    stl = st.series.reindex(d.index)

    levels = [("P", cpr.pivot), ("BC", cpr.bc), ("TC", cpr.tc), ("R1", cpr.r1), ("S1", cpr.s1)]
    lo = min(d["low"].min(), stl["supertrend"].min(), min(v for _, v in levels))
    hi = max(d["high"].max(), stl["supertrend"].max(), max(v for _, v in levels))
    span = (hi - lo) or 1.0
    lo, hi = lo - span * 0.06, hi + span * 0.06
    span = hi - lo

    def y(v: float) -> float:
        return PAD_T + (hi - v) / span * (H - PAD_T - PAD_B)

    img = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(img)
    dr.text((PAD_L, 8), f"{title}   {verdict}", fill=(230, 232, 236))

    plot_w = W - PAD_L - PAD_R
    step = plot_w / max(len(d), 1)
    body = max(1.0, step * 0.6)

    for name, value in levels:
        yy = y(value)
        colour = LEVELS[name]
        for x in range(PAD_L, PAD_L + int(plot_w), 6):   # dashed
            dr.line([(x, yy), (x + 3, yy)], fill=colour, width=1)
        dr.text((PAD_L + plot_w + 6, yy - 6), f"{name} {value:,.2f}", fill=colour)

    for i, (_, row) in enumerate(d.iterrows()):
        cx = PAD_L + i * step + step / 2
        colour = UP if row["close"] >= row["open"] else DOWN
        dr.line([(cx, y(row["high"])), (cx, y(row["low"]))], fill=colour, width=1)
        top, bot = y(max(row["open"], row["close"])), y(min(row["open"], row["close"]))
        dr.rectangle([cx - body / 2, top, cx + body / 2, max(bot, top + 1)], fill=colour)

    pts, prev_dir = [], None
    for i, (_, row) in enumerate(stl.iterrows()):
        if pd.isna(row["supertrend"]):
            continue
        cx = PAD_L + i * step + step / 2
        if row["direction"] != prev_dir and len(pts) > 1:
            dr.line(pts, fill=UP if prev_dir == "bull" else DOWN, width=2)
            pts = []
        pts.append((cx, y(row["supertrend"])))
        prev_dir = row["direction"]
    if len(pts) > 1:
        dr.line(pts, fill=UP if prev_dir == "bull" else DOWN, width=2)

    dr.text((PAD_L, H - 18), d.index[0].strftime("%d %b %y"), fill=DIM)
    dr.text((PAD_L + plot_w - 60, H - 18), d.index[-1].strftime("%d %b %y"), fill=DIM)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
