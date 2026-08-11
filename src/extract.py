"""Ticker extraction, per spec §6 step 2 and Q3.

Four passes: cashtag regex, prose LLM, quoted text, and vision over chart images.
Resolution is registry-only -- there is no fuzzy matching, deliberately. A fuzzy
matcher turning "BulkSOL" into SOL would render a confident chart with a verdict
for an asset nobody mentioned (spec §11).
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import requests
import yaml

import onchain

ALIASES = Path(__file__).resolve().parent.parent / "config" / "aliases.yaml"
CASHTAG = re.compile(r"\$([A-Za-z][A-Za-z0-9._-]{0,9})\b")
ASSET_CLASSES = ("crypto", "us_equity", "commodity_fx", "in_equity")


def _norm(token: str) -> str:
    """Lowercase, strip everything but letters and digits."""
    return re.sub(r"[^a-z0-9]", "", token.lower())


@dataclass(frozen=True)
class Mention:
    raw_token: str
    subject: str | None
    resolved_symbol: str | None
    asset_class: str | None
    method: str          # cashtag | llm | vision | alias
    source_field: str    # text | quoted_text | image
    confidence: float


class Registry:
    MIN_KEYWORD_LEN = 3

    def __init__(self, data: dict):
        self.stopwords = {str(w).lower() for w in data.get("stopwords", [])}
        self.keyword_exclude = {str(w).lower() for w in data.get("keyword_exclude", [])}
        self.subject_only = {k.lower(): v for k, v in (data.get("subject_only") or {}).items()}
        self.lookup: dict[str, tuple[str, str, str]] = {}
        for asset_class in ASSET_CLASSES:
            for token, spec in (data.get(asset_class) or {}).items():
                self.lookup[token.lower()] = (spec["symbol"], asset_class, spec["name"])

        # Punctuation-insensitive index. The LLM writes "HDFC Bank" and
        # "Dr. Reddy's Laboratories" where the registry keys are "hdfcbank" and
        # "drreddy"; without this both fall into the unresolved bucket despite
        # already being known. Still exact matching, just on a normalised key --
        # no fuzzy distance, so "BulkSOL" still cannot become "SOL".
        self.norm_lookup = {_norm(k): v for k, v in self.lookup.items()}
        self.norm_subject = {_norm(k): v for k, v in self.subject_only.items()}

    def keyword_terms(self) -> list[str]:
        """Registry keys safe to match in bare prose without a $ or an LLM."""
        terms = set(self.lookup) | set(self.subject_only)
        return sorted(
            (t for t in terms if len(t) >= self.MIN_KEYWORD_LEN and t not in self.keyword_exclude),
            key=len,
            reverse=True,  # longest first: "yt-bulksol" must beat "bulksol"
        )

    @classmethod
    def load(cls, path: Path = ALIASES) -> Registry:
        with open(path) as fh:
            return cls(yaml.safe_load(fh))

    def resolve(self, token: str, method: str, source_field: str) -> Mention | None:
        """Registry-only resolution. Unknown tokens stay unresolved, by design.

        One exception to registry-only: a Solana contract address IS the
        identity of an on-chain token — nothing to fuzzy-match, no registry
        entry needed. It resolves to `solana:<ca>` and the DEX APIs supply the
        symbol and name downstream.
        """
        if onchain.is_onchain_symbol(token.strip()):
            return Mention(token, None, onchain.to_symbol(token), "onchain",
                           method, source_field, 1.0)
        key = token.lower().lstrip("$").strip()
        if not key or key in self.stopwords:
            return None

        if key in self.lookup:
            symbol, asset_class, name = self.lookup[key]
            return Mention(token, name, symbol, asset_class, method, source_field, 1.0)
        if key in self.subject_only:
            return Mention(token, self.subject_only[key]["name"], None, None, method, source_field, 1.0)

        nkey = _norm(key)
        if nkey and nkey in self.norm_lookup:
            symbol, asset_class, name = self.norm_lookup[nkey]
            return Mention(token, name, symbol, asset_class, method, source_field, 0.9)
        if nkey and nkey in self.norm_subject:
            return Mention(token, self.norm_subject[nkey]["name"], None, None, method, source_field, 0.9)

        return Mention(token, None, None, None, method, source_field, 0.0)


def extract_cashtags(text: str, registry: Registry, source_field: str) -> list[Mention]:
    out = []
    for match in CASHTAG.findall(text or ""):
        m = registry.resolve(match, "cashtag", source_field)
        if m:
            out.append(m)
    return out


def extract_keywords(text: str, registry: Registry, source_field: str) -> list[Mention]:
    """Deterministic registry-key scan over bare prose.

    Not in the original spec, which fell back to cashtag-only without an API key.
    On the real feed that path found assets in 2 of 21 posts, because this list
    writes "gold and silver are over", not "$GC=F". Strictly better than
    cashtag-only, costs nothing, and never invents a symbol -- it can only match
    keys already in the registry.
    """
    if not (text or "").strip():
        return []
    lowered = text.lower()
    out, consumed = [], []
    for term in registry.keyword_terms():
        for match in re.finditer(rf"(?<![\w$]){re.escape(term)}(?![\w])", lowered):
            span = match.span()
            if any(span[0] < e and s < span[1] for s, e in consumed):
                continue  # already covered by a longer term
            consumed.append(span)
            m = registry.resolve(term, "alias", source_field)
            if m and (m.resolved_symbol or m.subject):
                out.append(m)
            break
    return out


# Methods gated by the LLM's incidental judgement. A posted contract address or
# chart screenshot is a deliberate act; text hits can be passing mentions.
GATED_METHODS = {"cashtag", "alias", "llm"}


def drop_incidental(mentions: list[Mention], incidental: set[str]) -> list[Mention]:
    """Drop text-pass mentions the LLM judged as having no market view."""
    if not incidental:
        return mentions
    kept = []
    for m in mentions:
        keys = {(m.resolved_symbol or "").lower(),
                m.raw_token.lower().lstrip("$"),
                (m.subject or "").lower()} - {""}
        if m.method in GATED_METHODS and keys & incidental:
            continue
        kept.append(m)
    return kept


def extract_contracts(text: str, source_field: str) -> list[Mention]:
    """Deterministic scan for bare Solana contract addresses (pump.fun posts)."""
    return [
        Mention(ca, None, onchain.to_symbol(ca), "onchain", "contract", source_field, 1.0)
        for ca in onchain.find_contracts(text or "")
    ]


PROSE_PROMPT = """Extract every financial asset mentioned in this social media post.

Include: stocks, ETFs, indices, cryptocurrencies, tokens, commodities, currencies.
Also include assets with no public market (farm tokens, yield tokens, prediction
markets) — name them exactly as written.

Exclude: company names used in passing with no trading context, product names,
usernames, and generic market talk ("the market", "alts").

Split the assets by whether the author expresses a market-relevant view:
- "assets": the author states or implies an opinion, position, prediction, or
  chart observation about the asset's price or market.
- "incidental": the asset (or its chain/company) appears only in passing —
  wallet/chain infrastructure, payments, airdrops or giveaways, follower and
  community talk, app features — with no view on its price.

Also judge the post's directional stance on the "assets".

Post:
---
{text}
---

Return JSON only:
{{"assets": ["..."], "incidental": ["..."], "sentiment": "bullish"|"bearish"|"neutral"}}"""

VISION_PROMPT = """This image is attached to a trading post. If it is a price
chart, read the instrument symbol from the chart header (e.g. "BTCUSDT",
"XAUUSD", "NIFTY", "Bitcoin / TetherUS").

Return JSON only:
{"symbol": "<symbol or null>", "is_chart": true|false}

Return null for symbol if this is not a price chart or the header is unreadable."""


def _client():
    import anthropic

    return anthropic.Anthropic()


def _json_from(text: str) -> dict:
    """Tolerates markdown-fenced JSON, which the CLI backend emits."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object in model output: {text[:200]!r}")
    return json.loads(text[start : end + 1])


# --- Model backends ------------------------------------------------------------
#
# `claude_cli` shells out to Claude Code in headless mode, which runs on the
# user's Max subscription rather than metered API credits. Slower (~9s text,
# ~17s per image) but free at the margin, and it needs no API key anywhere on
# disk. `api` uses the SDK and requires ANTHROPIC_API_KEY.
#
# Both are prompt-injection-contained by construction: tweet text and chart
# images are untrusted input, but the only thing either backend can return is a
# token that must then match a key already in aliases.yaml. A hostile image
# cannot conjure a symbol that is not in the registry.

CLI_TIMEOUT = 120


def _cli_call(prompt: str, model: str, image_path: str | None = None,
              attempts: int = 3) -> str:
    """Shell out to Claude Code headless, with retries.

    Under a 4-worker pool the CLI fails intermittently — 18 of 22 calls in one
    run, while the same calls succeed one at a time. Cause is transient
    (contention or throttling), not the prompt, so a short backoff recovers it.
    """
    cmd = ["claude", "-p", prompt, "--model", model, "--output-format", "text"]
    if image_path:
        cmd += ["--allowedTools", "Read"]

    last = ""
    for attempt in range(attempts):
        if attempt:
            time.sleep(2 * attempt)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=CLI_TIMEOUT)
        except subprocess.TimeoutExpired:
            last = f"timeout after {CLI_TIMEOUT}s"
            continue
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout
        last = f"exit {proc.returncode}: {(proc.stderr or proc.stdout)[-200:]}"
    raise RuntimeError(f"claude CLI failed after {attempts} attempts — {last}")


def backend_available(backend: str) -> bool:
    if backend == "api":
        return bool(os.environ.get("ANTHROPIC_API_KEY"))
    return shutil.which("claude") is not None


def extract_prose(text: str, registry: Registry, source_field: str, model: str,
                  backend: str = "claude_cli") -> tuple[list[Mention], str | None, set[str]]:
    """LLM pass over text. Returns (mentions, sentiment, incidental_keys).

    incidental_keys are lowercase names/symbols the model judged as mentioned
    without a market view — used to gate cashtag/keyword hits on the same tweet.
    """
    if not (text or "").strip():
        return [], None, set()

    prompt = PROSE_PROMPT.format(text=text)
    if backend == "claude_cli":
        raw = _cli_call(prompt, model)
    else:
        resp = _client().messages.create(
            model=model, max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text

    data = _json_from(raw)
    mentions = [m for a in data.get("assets", []) if (m := registry.resolve(a, "llm", source_field))]
    signal = {(m.resolved_symbol or m.raw_token).lower() for m in mentions}
    incidental: set[str] = set()
    for name in data.get("incidental", []):
        keys = {str(name).lower().lstrip("$")}
        m = registry.resolve(str(name), "llm", source_field)
        if m and m.resolved_symbol:
            keys.add(m.resolved_symbol.lower())
        if keys & signal:  # a market-view listing wins over incidental
            continue
        incidental |= keys
    sentiment = data.get("sentiment")
    return mentions, (sentiment if sentiment in ("bullish", "bearish", "neutral") else None), incidental


def extract_vision(image_url: str, registry: Registry, model: str,
                   backend: str = "claude_cli") -> list[Mention]:
    """Read the instrument symbol off a chart screenshot (Q3 tier 2)."""
    resp = requests.get(image_url, timeout=30)
    resp.raise_for_status()
    media_type = resp.headers.get("content-type", "image/jpeg").split(";")[0]
    if media_type not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
        return []

    if backend == "claude_cli":
        suffix = {"image/png": ".png", "image/gif": ".gif", "image/webp": ".webp"}.get(media_type, ".jpg")
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as fh:
            fh.write(resp.content)
            tmp = fh.name
        try:
            raw = _cli_call(f"Read the image at {tmp} . {VISION_PROMPT}", model, image_path=tmp)
        finally:
            os.unlink(tmp)
    else:
        message = _client().messages.create(
            model=model, max_tokens=256,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": media_type,
                        "data": base64.standard_b64encode(resp.content).decode(),
                    }},
                    {"type": "text", "text": VISION_PROMPT},
                ],
            }],
        )
        raw = message.content[0].text

    data = _json_from(raw)
    symbol = data.get("symbol")
    if not data.get("is_chart") or not symbol:
        return []

    # Chart headers carry quote currencies and vendor decoration; try the whole
    # string first, then progressively stripped forms. Still registry-only.
    for candidate in _symbol_candidates(str(symbol)):
        m = registry.resolve(candidate, "vision", "image")
        if m and (m.resolved_symbol or m.subject):
            return [m]
    return [Mention(str(symbol), None, None, None, "vision", "image", 0.0)]


def _symbol_candidates(symbol: str) -> list[str]:
    s = symbol.strip()
    out = [s]
    for suffix in ("USDT", "USDC", "USD", "PERP", "/USDT", "/USD"):
        if s.upper().endswith(suffix) and len(s) > len(suffix):
            out.append(s[: -len(suffix)].rstrip("/ "))
    out.extend(part for part in re.split(r"[/\s|·-]+", s) if part)
    seen, unique = set(), []
    for c in out:
        if c and c.lower() not in seen:
            seen.add(c.lower())
            unique.append(c)
    return unique


def dedupe(mentions: list[Mention]) -> list[Mention]:
    """One row per resolved target, preferring the highest-confidence finder."""
    best: dict[str, Mention] = {}
    order = {"contract": 4, "cashtag": 3, "vision": 2, "llm": 1, "alias": 0}
    for m in mentions:
        key = (m.resolved_symbol or m.subject or m.raw_token).lower()
        current = best.get(key)
        if current is None or (m.confidence, order.get(m.method, 0)) > (
            current.confidence, order.get(current.method, 0)
        ):
            best[key] = m
    return list(best.values())
