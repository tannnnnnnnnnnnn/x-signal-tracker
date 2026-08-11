"""Verdict grid, per spec §8."""

from __future__ import annotations

from dataclasses import dataclass

from indicators import CPR, Supertrend, is_narrow_cpr

# (supertrend direction, cpr position) -> verdict
GRID = {
    ("bull", "above"): "Strong bullish",
    ("bull", "inside"): "Bullish, indecisive",
    ("bull", "below"): "Conflict",
    ("bear", "above"): "Conflict",
    ("bear", "inside"): "Bearish, indecisive",
    ("bear", "below"): "Strong bearish",
}


def cpr_position(close: float, cpr: CPR) -> str:
    """Band-edge comparison. Spec §8 — label-based comparison breaks on inversion."""
    if close > cpr.top:
        return "above"
    if close < cpr.bottom:
        return "below"
    return "inside"


@dataclass(frozen=True)
class Verdict:
    verdict: str
    st_direction: str
    cpr_position: str
    narrow_cpr: bool
    inverted_cpr: bool
    conflict: bool

    @property
    def badges(self) -> list[str]:
        out = []
        if self.narrow_cpr:
            out.append("narrow CPR")
        if self.inverted_cpr:
            out.append("inverted CPR")
        return out


def judge(close: float, st: Supertrend, cpr: CPR, width_history: list[float]) -> Verdict:
    position = cpr_position(close, cpr)
    text = GRID[(st.direction, position)]
    return Verdict(
        verdict=text,
        st_direction=st.direction,
        cpr_position=position,
        narrow_cpr=is_narrow_cpr(cpr.width, width_history),
        inverted_cpr=cpr.inverted,
        conflict=text == "Conflict",
    )


def sentiment_disagrees(sentiment: str | None, verdict: Verdict) -> bool:
    """Tweet sentiment against the mechanical verdict (spec §8).

    The single most useful line on a card, so it is deliberately conservative:
    only a clear directional clash counts.
    """
    if sentiment not in ("bullish", "bearish"):
        return False
    if verdict.conflict:
        return False
    bullish_verdict = verdict.verdict.startswith(("Strong bullish", "Bullish"))
    return (sentiment == "bullish") != bullish_verdict
