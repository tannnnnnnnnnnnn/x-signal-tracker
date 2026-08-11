"""Telegram digest. Spec §6 step 6.

No-ops cleanly when TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are unset, so the rest
of the pipeline never depends on it being configured.
"""

from __future__ import annotations

import html
import os

import requests

API = "https://api.telegram.org/bot{token}/{method}"
TIMEOUT = 30
MAX_PHOTOS = 8   # a phone digest stops being a digest past this


def configured() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))


def _post(method: str, data: dict, files: dict | None = None) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    resp = requests.post(
        API.format(token=token, method=method),
        data={"chat_id": os.environ["TELEGRAM_CHAT_ID"], **data},
        files=files,
        timeout=TIMEOUT,
    )
    if not resp.ok:
        raise RuntimeError(f"telegram {method} {resp.status_code}: {resp.text[:200]}")


def send_message(text: str) -> None:
    _post("sendMessage", {"text": text, "parse_mode": "HTML",
                          "disable_web_page_preview": "true"})


def send_photo(png: bytes, caption: str) -> None:
    _post("sendPhoto", {"caption": caption, "parse_mode": "HTML"},
          files={"photo": ("chart.png", png, "image/png")})


def _line(c: dict) -> str:
    badges = f" · {', '.join(c['verdict']['badges'])}" if c["verdict"]["badges"] else ""
    clash = " ⚠️ disagrees with the post" if c.get("disagrees") else ""
    return (
        f"<b>{html.escape(c['symbol'])}</b> {c['verdict']['verdict']}{badges}{clash}\n"
        f"<i>@{html.escape(c['handle'])}</i> · "
        f"<a href=\"{html.escape(c['url'])}\">post</a>"
    )


def send_digest(cards: list[dict], unresolved: list[dict], stats: dict,
                warnings: list[str], png_for=None) -> None:
    """One summary message, then a photo per charted card up to MAX_PHOTOS."""
    charted = [c for c in cards if c["kind"] == "chart"]
    nochart = [c for c in cards if c["kind"] == "nochart"]

    head = [f"<b>X Signal Tracker</b> — {stats['kept']} posts, {len(charted)} charted"]
    if warnings:
        head.append("\n⚠️ " + "\n⚠️ ".join(html.escape(w) for w in warnings[:3]))
    if charted:
        head.append("\n" + "\n\n".join(_line(c) for c in charted))
    if nochart:
        head.append("\n<b>No price feed:</b> " + ", ".join(
            html.escape(c["subject"]) for c in nochart))
    if unresolved:
        head.append(f"\n<i>{len(unresolved)} unresolved</i>")
    if not charted and not nochart:
        head.append("\nNo assets mentioned in the last 24 hours.")

    send_message("\n".join(head))

    if png_for is None:
        return
    for c in charted[:MAX_PHOTOS]:
        try:
            send_photo(png_for(c), f"<b>{html.escape(c['symbol'])}</b> — {c['verdict']['verdict']}")
        except Exception:
            pass  # a failed image must never lose the digest that already sent


def send_failure(message: str) -> None:
    if configured():
        try:
            send_message(f"🔴 <b>X Signal Tracker failed</b>\n{html.escape(message)}")
        except Exception:
            pass
