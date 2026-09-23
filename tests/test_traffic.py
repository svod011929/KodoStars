"""Greetings rotation and traffic-campaign counters."""

import pytest

from app.services import campaigns, greetings
from app.services.errors import ValidationError


@pytest.mark.asyncio
async def test_greetings_rotate_least_shown(session) -> None:
    first = await greetings.create_greeting(session, body="one")
    second = await greetings.create_greeting(session, body="two", button_text="Go", button_url="https://t.me/x")
    picked = await greetings.pick_greeting(session)
    assert picked is not None and picked.id == first.id and picked.shows == 1
    picked = await greetings.pick_greeting(session)
    assert picked is not None and picked.id == second.id
    await greetings.toggle_greeting(session, first.id)
    picked = await greetings.pick_greeting(session)
    assert picked is not None and picked.id == second.id
    with pytest.raises(ValidationError):
        await greetings.create_greeting(session, body="x", button_text="only text")


def test_parse_campaign_payload_ignores_refs_and_promos() -> None:
    assert campaigns.parse_campaign_payload("c_summer") == "SUMMER"
    assert campaigns.parse_campaign_payload("utm_ab_1") == "AB_1"
    assert campaigns.parse_campaign_payload("ref_15") is None
    assert campaigns.parse_campaign_payload("promo_GIFT") is None
    assert campaigns.parse_campaign_payload("c_x") is None


@pytest.mark.asyncio
async def test_campaign_counts_clicks_and_unique_users(session) -> None:
    await campaigns.record_hit(session, code="june", user_id=1, is_new=True)
    await campaigns.record_hit(session, code="JUNE", user_id=1, is_new=False)
    await campaigns.record_hit(session, code="june", user_id=2, is_new=True)
    rows = await campaigns.list_campaigns(session)
    assert len(rows) == 1 and rows[0].code == "JUNE"
    stats = await campaigns.campaign_stats(session, rows[0].id)
    assert stats.clicks_all == 3
    assert stats.users_all == 2
    assert stats.clicks_day == 3
    assert campaigns.campaign_link("Bot", "june") == "https://t.me/Bot?start=c_JUNE"
