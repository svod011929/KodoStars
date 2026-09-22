"""Promo deep-link helpers."""

from app.services.promo import activation_link, normalize_code, parse_promo_payload


def test_parse_promo_payload() -> None:
    assert parse_promo_payload("promo_ABCD12") == "ABCD12"
    assert parse_promo_payload("PROMO_ab-cd") == "AB-CD"
    assert parse_promo_payload("ref_1") is None
    assert parse_promo_payload("") is None


def test_activation_link() -> None:
    assert activation_link("MyBot", "hello") == "https://t.me/MyBot?start=promo_HELLO"
    assert activation_link("@MyBot", normalize_code("x1")) == "https://t.me/MyBot?start=promo_X1"
