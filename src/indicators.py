"""Supertrend and SwingCPR, per docs/specs/2026-08-06-x-signal-tracker-design.md §7.

Both are computed from daily OHLCV. Nothing here touches the network.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

ATR_PERIOD = 22
ATR_MULTIPLIER = 3.0
CPR_WIDTH_LOOKBACK = 6


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """Pine's ta.tr(true): bar 0 falls back to high-low, having no prior close."""
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    tr.iloc[0] = high.iloc[0] - low.iloc[0]
    return tr


def wilder_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = ATR_PERIOD) -> pd.Series:
    """ATR via Wilder's RMA, matching Pine's ta.atr exactly.

    Not `ewm(alpha=1/period)`: Pine's ta.rma seeds with an SMA of the first
    `period` values, then recurses. Plain ewm seeds from bar 0 instead, which
    leaves a small persistent offset. Spec §7.1 — SMA or EMA here shifts every
    downstream value.
    """
    tr = true_range(high, low, close)
    n = len(tr)
    out = np.full(n, np.nan)
    if n < period:
        return pd.Series(out, index=high.index)

    values = tr.to_numpy()
    out[period - 1] = values[:period].mean()
    for i in range(period, n):
        out[i] = (out[i - 1] * (period - 1) + values[i]) / period
    return pd.Series(out, index=high.index)


def ema(close: pd.Series, period: int) -> pd.Series:
    """EMA matching Pine's ta.ema: seeded with an SMA of the first `period` bars.

    NaN until bar `period - 1`; a series shorter than `period` is all NaN, which
    is how a young token ends up with no EMA200 line rather than a wrong one.
    """
    n = len(close)
    out = np.full(n, np.nan)
    if n < period:
        return pd.Series(out, index=close.index)

    values = close.to_numpy(dtype=float)
    out[period - 1] = values[:period].mean()
    alpha = 2.0 / (period + 1)
    for i in range(period, n):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return pd.Series(out, index=close.index)


@dataclass(frozen=True)
class Supertrend:
    value: float
    direction: str  # "bull" | "bear"
    series: pd.DataFrame


def supertrend(
    df: pd.DataFrame,
    period: int = ATR_PERIOD,
    multiplier: float = ATR_MULTIPLIER,
) -> Supertrend:
    """Supertrend over a DataFrame indexed by date with open/high/low/close columns."""
    high, low, close = df["high"], df["low"], df["close"]
    atr = wilder_atr(high, low, close, period)

    hl2 = (high + low) / 2
    basic_upper = hl2 + multiplier * atr
    basic_lower = hl2 - multiplier * atr

    n = len(df)
    final_upper = np.full(n, np.nan)
    final_lower = np.full(n, np.nan)
    direction = np.full(n, None, dtype=object)  # None, not "", so dropna() works
    line = np.full(n, np.nan)

    bu, bl, cl = basic_upper.to_numpy(), basic_lower.to_numpy(), close.to_numpy()

    first = int(np.argmax(~np.isnan(bu))) if np.any(~np.isnan(bu)) else n
    if first >= n:
        raise ValueError(f"not enough bars for ATR({period}): got {n}")

    final_upper[first] = bu[first]
    final_lower[first] = bl[first]
    direction[first] = "bull" if cl[first] > bu[first] else "bear"
    line[first] = final_lower[first] if direction[first] == "bull" else final_upper[first]

    for i in range(first + 1, n):
        # Bands ratchet: they only tighten, and reset when price closes through them.
        final_upper[i] = (
            bu[i] if (bu[i] < final_upper[i - 1] or cl[i - 1] > final_upper[i - 1]) else final_upper[i - 1]
        )
        final_lower[i] = (
            bl[i] if (bl[i] > final_lower[i - 1] or cl[i - 1] < final_lower[i - 1]) else final_lower[i - 1]
        )

        if cl[i] > final_upper[i - 1]:
            direction[i] = "bull"
        elif cl[i] < final_lower[i - 1]:
            direction[i] = "bear"
        else:
            direction[i] = direction[i - 1]

        line[i] = final_lower[i] if direction[i] == "bull" else final_upper[i]

    series = pd.DataFrame(
        {"supertrend": line, "direction": direction, "atr": atr.to_numpy()},
        index=df.index,
    )
    return Supertrend(value=float(line[-1]), direction=str(direction[-1]), series=series)


@dataclass(frozen=True)
class CPR:
    """Monthly CPR.

    SwingCPR plots five lines in this order: **pivot, BC, TC, R1, S1**.
    Lines 4 and 5 are pivot-derived support/resistance, NOT the prior high/low.

    Beware the identity `(r1 + s1) / 2 == tc`, which holds for every CPR by
    algebra (`(2p-L + 2p-H)/2 = 2p - BC = TC`). It is not evidence of anything
    and must never be used to identify which plotted line is which.
    """

    pivot: float
    bc: float
    tc: float
    r1: float             # 2*pivot - prior_low
    s1: float             # 2*pivot - prior_high
    prior_high: float
    prior_low: float
    prior_close: float
    width: float          # fraction of pivot, always non-negative
    inverted: bool        # tc < bc
    period_label: str     # e.g. "2026-07"

    @property
    def top(self) -> float:
        """Upper band edge. Spec §8 — never assume tc > bc."""
        return max(self.tc, self.bc)

    @property
    def bottom(self) -> float:
        return min(self.tc, self.bc)


def _monthly_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    return df.resample("MS").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    ).dropna()


def swing_cpr(df: pd.DataFrame, asof: pd.Timestamp | None = None) -> CPR:
    """Monthly CPR (spec §7.2, Q1 resolved) for the month containing `asof`.

    Levels derive from the *prior* calendar month and hold constant all month.
    """
    monthly = _monthly_ohlc(df)
    if len(monthly) < 2:
        raise ValueError(f"need >=2 calendar months of data, got {len(monthly)}")

    asof = pd.Timestamp(asof) if asof is not None else df.index[-1]
    current_start = pd.Timestamp(year=asof.year, month=asof.month, day=1)

    prior = monthly[monthly.index < current_start]
    if prior.empty:
        raise ValueError(f"no completed month before {current_start.date()}")
    row = prior.iloc[-1]

    h, low_, c = float(row["high"]), float(row["low"]), float(row["close"])
    pivot = (h + low_ + c) / 3
    bc = (h + low_) / 2
    tc = 2 * pivot - bc

    return CPR(
        pivot=pivot,
        bc=bc,
        tc=tc,
        r1=2 * pivot - low_,
        s1=2 * pivot - h,
        prior_high=h,
        prior_low=low_,
        prior_close=c,
        width=abs(tc - bc) / pivot,
        inverted=tc < bc,
        period_label=f"{prior.index[-1].year:04d}-{prior.index[-1].month:02d}",
    )


def cpr_history(df: pd.DataFrame) -> list[dict]:
    """Per-month CPR segments for chart drawing.

    One dict per month that has a completed prior month: start/end timestamps of
    the month the levels apply to, plus the five SwingCPR levels. The final
    segment is the in-progress month (same levels swing_cpr returns).
    """
    monthly = _monthly_ohlc(df)
    out = []
    for i in range(1, len(monthly)):
        row = monthly.iloc[i - 1]
        h, low_, c = float(row["high"]), float(row["low"]), float(row["close"])
        pivot = (h + low_ + c) / 3
        bc = (h + low_) / 2
        tc = 2 * pivot - bc
        start = monthly.index[i]
        out.append({
            "start": start,
            "end": start + pd.offsets.MonthBegin(1),
            "pivot": pivot, "bc": bc, "tc": tc,
            "r1": 2 * pivot - low_, "s1": 2 * pivot - h,
        })
    return out


def cpr_width_history(df: pd.DataFrame, lookback: int = CPR_WIDTH_LOOKBACK) -> list[float]:
    """Widths of the `lookback` completed months before the current one."""
    monthly = _monthly_ohlc(df)
    completed = monthly.iloc[:-1]  # the in-progress month is not a valid input
    widths = []
    for _, row in completed.tail(lookback).iterrows():
        h, low_, c = float(row["high"]), float(row["low"]), float(row["close"])
        pivot = (h + low_ + c) / 3
        bc = (h + low_) / 2
        widths.append(abs(2 * pivot - 2 * bc) / pivot)
    return widths


def is_narrow_cpr(current_width: float, history: list[float]) -> bool:
    """Narrow when below the trailing average. Undefined with no history -> False."""
    if not history:
        return False
    return current_width < (sum(history) / len(history))
