"""The fake Telegram session refuses message HTML the way the Bot API does."""

import pytest

from tests.fake_telegram import telegram_html_error


@pytest.mark.parametrize(
    "text",
    [
        "plain & simple > fine",
        "<b>bold</b> <i>it</i> <code>x</code>",
        '<a href="https://t.me/x">link</a>',
        '<tg-emoji emoji-id="5368324170671202286">👍</tg-emoji>',
        "<blockquote expandable><b>nested</b></blockquote>",
        "&lt;tg-emoji&gt;",
    ],
)
def test_accepts_what_telegram_accepts(text: str) -> None:
    assert telegram_html_error(text) is None


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("numeric id / <tg-emoji>…", "tg-emoji without emoji-id"),
        ("a < b", "unescaped '<'"),
        ("line<br>break", "unsupported tag <br>"),
        ("<b>bold", "unclosed <b>"),
        ("<b><i>x</b></i>", "unmatched </b>"),
        ("x</b>", "unmatched </b>"),
    ],
)
def test_refuses_what_telegram_refuses(text: str, error: str) -> None:
    assert telegram_html_error(text) == error
