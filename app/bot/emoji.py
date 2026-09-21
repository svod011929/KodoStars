"""Telegram premium custom-emoji helpers.

Messages use ``<tg-emoji emoji-id="…">fallback</tg-emoji>``.
Inline / reply keyboard buttons use ``icon_custom_emoji_id`` and must not
include regular emoji characters in ``text``.
"""

from __future__ import annotations

import re

# Default premium glyph for internal Stars currency (overridable at runtime).
DEFAULT_CURRENCY_ID = "5904462880941545555"
DEFAULT_CURRENCY_FALLBACK = "⭐"

_currency_id: str = DEFAULT_CURRENCY_ID
_currency_fallback: str = DEFAULT_CURRENCY_FALLBACK

# key → (custom_emoji_id, unicode fallback)
CATALOG: dict[str, tuple[str, str]] = {
    "settings": ("5870982283724328568", "⚙️"),
    "profile": ("5870994129244131212", "👤"),
    "people": ("5870772616305839506", "👥"),
    "person_ok": ("5891207662678317861", "👤"),
    "person_no": ("5893192487324880883", "👤"),
    "file": ("5870528606328852614", "📁"),
    "smile": ("5870764288364252592", "🙂"),
    "growth": ("5870930636742595124", "📊"),
    "stats": ("5870921681735781843", "📊"),
    "home": ("5873147866364514353", "🏘"),
    "lock": ("6037249452824072506", "🔒"),
    "unlock": ("6037496202990194718", "🔓"),
    "megaphone": ("6039422865189638057", "📣"),
    "check": ("5870633910337015697", "✅"),
    "cross": ("5870657884844462243", "❌"),
    "pencil": ("5870676941614354370", "🖋"),
    "trash": ("5870875489362513438", "🗑"),
    "down": ("5893057118545646106", "📰"),
    "clip": ("6039451237743595514", "📎"),
    "link": ("5769289093221454192", "🔗"),
    "info": ("6028435952299413210", "ℹ"),
    "bot": ("6030400221232501136", "🤖"),
    "eye": ("6037397706505195857", "👁"),
    "hidden": ("6037243349675544634", "👁"),
    "upload": ("5963103826075456248", "⬆"),
    "download": ("6039802767931871481", "⬇"),
    "bell": ("6039486778597970865", "🔔"),
    "gift": ("6032644646587338669", "🎁"),
    "clock": ("5983150113483134607", "⏰"),
    "party": ("6041731551845159060", "🎉"),
    "font": ("5870801517140775623", "🔗"),
    "write": ("5870753782874246579", "✍"),
    "photo": ("6035128606563241721", "🖼"),
    "pin": ("6042011682497106307", "📍"),
    "wallet": ("5769126056262898415", "👛"),
    "box": ("5884479287171485878", "📦"),
    "cryptobot": ("5260752406890711732", "👾"),
    "calendar": ("5890937706803894250", "📅"),
    "tag": ("5886285355279193209", "🏷"),
    "time_ago": ("5775896410780079073", "🕓"),
    "apps": ("5778672437122045013", "📦"),
    "brush": ("6050679691004612757", "🖌"),
    "add_text": ("5771851822897566479", "🔡"),
    "format": ("5778479949572738874", "↔"),
    "coin": ("5904462880941545555", "🪙"),
    "send_money": ("5890848474563352982", "🪙"),
    "recv_money": ("5879814368572478751", "🏧"),
    "code": ("5940433880585605708", "🔨"),
    "loading": ("5345906554510012647", "🔄"),
    # UI aliases (same ids, alternate unicode that appears in texts/buttons)
    "star": (DEFAULT_CURRENCY_ID, DEFAULT_CURRENCY_FALLBACK),
    "money": ("5904462880941545555", "💰"),
    "gem": ("5904462880941545555", "💎"),
    "shield": ("6037249452824072506", "🛡"),
    "withdraw": ("5890848474563352982", "💸"),
    "promo": ("5886285355279193209", "🎟"),
    "tasks": ("5870528606328852614", "📋"),
    "boost": ("5963103826075456248", "🚀"),
    "top": ("5870930636742595124", "🏆"),
    "medal": ("5870930636742595124", "🏅"),
    "help": ("6028435952299413210", "❓"),
    "admin": ("5940433880585605708", "🛠"),
    "users": ("5870772616305839506", "👥"),
    "broadcast": ("6039422865189638057", "📣"),
    "payments": ("5769126056262898415", "💳"),
    "audit": ("5870528606328852614", "🧾"),
    "fraud": ("6037397706505195857", "🕵️"),
    "data": ("5884479287171485878", "🗂"),
    "ban": ("5870657884844462243", "🚫"),
    "unban": ("5870633910337015697", "♻️"),
    "plus": ("5870633910337015697", "➕"),
    "minus": ("5870657884844462243", "➖"),
    "refresh": ("5345906554510012647", "🔄"),
    "back": ("5893057118545646106", "◁"),
    "next": ("5963103826075456248", "›"),
    "subscribe": ("6039451237743595514", "➕"),
    "device": ("6037249452824072506", "🛡"),
    "fire": ("6041731551845159060", "🔥"),
    "sparkle": ("6041731551845159060", "✨"),
    "warn": ("5983150113483134607", "⚠️"),
    "ok_green": ("5870633910337015697", "🟢"),
    "off": ("5870657884844462243", "⚪"),
    "wait": ("5983150113483134607", "⏳"),
    "doc": ("5870528606328852614", "📄"),
    "scroll": ("5870528606328852614", "📜"),
    "mail": ("6039451237743595514", "📨"),
    "share": ("5963103826075456248", "📤"),
    "pin_task": ("6042011682497106307", "📌"),
    "zap": ("5983150113483134607", "⚡"),
    "target": ("6042011682497106307", "🎯"),
    "home_alt": ("5873147866364514353", "🏠"),
    "stop": ("5870657884844462243", "⛔"),
    "no_entry": ("5870657884844462243", "🔴"),
    "undo": ("5345906554510012647", "↩️"),
    "letter": ("6039422865189638057", "✉️"),
    "play": ("5963103826075456248", "▶️"),
    "stop_btn": ("5870657884844462243", "⏹"),
    "twins": ("5870772616305839506", "👯"),
    "handshake": ("5891207662678317861", "🤝"),
    "left": ("5893057118545646106", "◀️"),
    "right": ("5963103826075456248", "▶️"),
    "cross_light": ("5870657884844462243", "✖"),
    "gear": ("5870982283724328568", "⚙️"),
    "pencil_alt": ("5870676941614354370", "✏️"),
    "gold": ("5870930636742595124", "🥇"),
    "silver": ("5870930636742595124", "🥈"),
    "bronze": ("5870930636742595124", "🥉"),
}

# Longest-first so multi-codepoint sequences match before single chars.
_UNICODE_TO_KEY: list[tuple[str, str]] = sorted(
    ((fallback, key) for key, (_eid, fallback) in CATALOG.items()),
    key=lambda item: len(item[0]),
    reverse=True,
)

# Deduplicate identical unicode → keep first (longest-order) mapping.
_SEEN_UNI: set[str] = set()
_UNICODE_UNIQUE: list[tuple[str, str]] = []
for _uni, _key in _UNICODE_TO_KEY:
    if _uni in _SEEN_UNI:
        continue
    _SEEN_UNI.add(_uni)
    _UNICODE_UNIQUE.append((_uni, _key))


def apply_currency(emoji_id: str, fallback: str = DEFAULT_CURRENCY_FALLBACK) -> None:
    """Swap the live currency glyph used in messages and ``icon="star"`` buttons."""
    global _currency_id, _currency_fallback
    eid = (emoji_id or "").strip() or DEFAULT_CURRENCY_ID
    fb = (fallback or "").strip() or DEFAULT_CURRENCY_FALLBACK
    _currency_id = eid
    _currency_fallback = fb


def currency_id() -> str:
    return _currency_id


def currency_fallback() -> str:
    return _currency_fallback


def currency() -> str:
    return f'<tg-emoji emoji-id="{_currency_id}">{_currency_fallback}</tg-emoji>'


def id_of(key: str) -> str:
    if key == "star":
        return _currency_id
    return CATALOG[key][0]


def fallback_of(key: str) -> str:
    if key == "star":
        return _currency_fallback
    return CATALOG[key][1]


def html(key: str) -> str:
    """Premium emoji markup for message HTML (parse_mode=HTML)."""
    if key == "star":
        return currency()
    eid, fb = CATALOG[key]
    return f'<tg-emoji emoji-id="{eid}">{fb}</tg-emoji>'


def star() -> str:
    return currency()


def premiumize(text: str) -> str:
    """Replace known unicode emoji in a message with ``<tg-emoji>`` tags."""
    if not text or "<tg-emoji" in text:
        return text
    out = text
    # Currency glyphs → live override (placeholder avoids re-matching fallback inside the tag).
    currency_glyphs = {g for g in (_currency_fallback, DEFAULT_CURRENCY_FALLBACK) if g}
    if currency_glyphs:
        marker = "\0CURRENCY\0"
        for glyph in sorted(currency_glyphs, key=len, reverse=True):
            out = out.replace(glyph, marker)
        out = out.replace(marker, currency())
    for uni, key in _UNICODE_UNIQUE:
        if key == "star" or uni in currency_glyphs:
            continue
        if uni in out:
            out = out.replace(uni, html(key))
    return out


def split_icon(text: str) -> tuple[str, str | None]:
    """Strip a leading known emoji from button label → (plain_text, icon_id)."""
    raw = text or ""
    if _currency_fallback and raw.startswith(_currency_fallback):
        rest = raw[len(_currency_fallback) :].lstrip(" \u00a0")
        return rest or raw, _currency_id
    for uni, key in _UNICODE_UNIQUE:
        if raw.startswith(uni):
            rest = raw[len(uni) :].lstrip(" \u00a0")
            return rest or raw, id_of(key)
    # Generic leading symbol (e.g. ·) — drop it, no premium icon.
    match = re.match(r"^([^\w\s]+)\s*(.*)$", raw)
    if match and match.group(2):
        return match.group(2), None
    return raw, None
