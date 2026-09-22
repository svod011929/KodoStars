"""End-to-end flows through the real dispatcher with a fake Telegram session."""

import asyncio

import pytest
import pytest_asyncio
from aiogram.methods import (
    AnswerPreCheckoutQuery,
    CopyMessage,
    EditMessageText,
    SendDocument,
    SendInvoice,
    SendMessage,
)
from sqlalchemy import select

from app.db.models import (
    Broadcast,
    BroadcastStatus,
    LedgerKind,
    ReferralEdge,
    User,
    Withdrawal,
    WithdrawalStatus,
)
from app.services import devices, ledger, payments, promo, referrals
from app.services.fragment import FragmentPurchase
from tests.conftest import ADMIN_ID, OTHER_ID, USER_ID, BotHarness
from tests.fake_telegram import (
    callback_update,
    message_update,
    pre_checkout_update,
    successful_payment_update,
)

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(autouse=True, loop_scope="module")
async def _clean_state(harness: BotHarness) -> None:
    await harness.reset()


async def _balance(h: BotHarness, user_id: int) -> int:
    async with h.factory() as session:
        return await ledger.get_balance(session, user_id)


async def _start(h: BotHarness, user_id: int, payload: str = "") -> None:
    text = f"/start {payload}".strip()
    await h.feed(message_update(user_id, text))


@pytest.mark.asyncio
async def test_start_creates_user_credits_signup_and_shows_home(harness: BotHarness) -> None:
    h = harness
    await _start(h, USER_ID)
    home = h.tg.last_text(USER_ID)
    assert "KodoStars" in home
    assert f"start=ref_{USER_ID}" in home
    assert await _balance(h, USER_ID) == h.settings.signup_bonus
    async with h.factory() as session:
        user = await session.get(User, USER_ID)
        assert user is not None and user.started_at is not None
        assert user.last_op_ok_at is not None


@pytest.mark.asyncio
async def test_op_gate_requires_device_before_sponsors(harness: BotHarness) -> None:
    h = harness
    h.settings.web_public_url = "https://mini.example"
    h.settings.device_check_for_op = True
    await _start(h, USER_ID)
    assert "Сначала подтвердите устройство" in h.tg.last_text(USER_ID)
    keyboard = h.tg.sent(SendMessage)[-1].reply_markup
    assert keyboard is not None
    assert keyboard.inline_keyboard[0][0].web_app.url == "https://mini.example/verify"

    # Regular menu callbacks are blocked the same way (no PiarFlow call yet).
    await h.feed(callback_update(USER_ID, "menu:daily"))
    assert "Сначала подтвердите устройство" in h.tg.last_text(USER_ID)

    # Admins bypass the gate entirely.
    await _start(h, ADMIN_ID)
    assert "KodoStars" in h.tg.last_text(ADMIN_ID)


@pytest.mark.asyncio
async def test_referral_attribution_only_on_first_start(harness: BotHarness) -> None:
    h = harness
    await _start(h, ADMIN_ID)
    await _start(h, USER_ID, f"ref_{ADMIN_ID}")
    async with h.factory() as session:
        user = await session.get(User, USER_ID)
        assert user.referred_by_id == ADMIN_ID
    # Referrer gets a "new friend" notification.
    assert any("новый друг" in text for text in h.tg.texts(ADMIN_ID))

    await _start(h, OTHER_ID)  # organic
    await _start(h, OTHER_ID, f"ref_{ADMIN_ID}")  # late click must not attribute
    async with h.factory() as session:
        other = await session.get(User, OTHER_ID)
        assert other.referred_by_id is None


@pytest.mark.asyncio
async def test_concurrent_double_start_creates_one_referral_edge(harness: BotHarness) -> None:
    """Regression for the production alert: two /start ref_… updates processed at once
    raised ``UNIQUE constraint failed: referral_edges…``. Per-user serialisation makes
    the second one a plain repeat."""
    h = harness
    await _start(h, ADMIN_ID)
    first = message_update(USER_ID, f"/start ref_{ADMIN_ID}", message_id=10)
    second = message_update(USER_ID, f"/start ref_{ADMIN_ID}", message_id=11)
    await asyncio.gather(h.feed(first), h.feed(second))

    async with h.factory() as session:
        edges = (
            (await session.execute(select(ReferralEdge).where(ReferralEdge.referee_id == USER_ID)))
            .scalars()
            .all()
        )
        assert [(e.referrer_id, e.level) for e in edges] == [(ADMIN_ID, 1)]
        user = await session.get(User, USER_ID)
        assert user.referred_by_id == ADMIN_ID
    assert not any("Ошибка в боте" in text for text in h.tg.texts(ADMIN_ID))
    assert sum("новый друг" in text for text in h.tg.texts(ADMIN_ID)) == 1
    assert sum("KodoStars" in text for text in h.tg.texts(USER_ID)) == 2


@pytest.mark.asyncio
async def test_concurrent_double_withdraw_creates_one_request(harness: BotHarness) -> None:
    h = harness
    await _start(h, ADMIN_ID)
    await _start(h, USER_ID)
    async with h.factory() as session:
        await ledger.credit(session, user_id=USER_ID, amount=200, kind=LedgerKind.TASK)
        await session.commit()
    await asyncio.gather(
        h.feed(callback_update(USER_ID, "wd:g:g50", message_id=20)),
        h.feed(callback_update(USER_ID, "wd:g:g50", message_id=21)),
    )
    async with h.factory() as session:
        requests = (
            (await session.execute(select(Withdrawal).where(Withdrawal.user_id == USER_ID))).scalars().all()
        )
        assert len(requests) == 1
    assert await _balance(h, USER_ID) == 205 - 50
    assert any("уже есть открытая заявка" in text for text in h.tg.texts(USER_ID))


@pytest.mark.asyncio
async def test_device_check_button_and_gating_in_ui(harness: BotHarness) -> None:
    h = harness
    h.settings.web_public_url = "https://mini.example"
    # Home menu with device button: mark OP cache fresh so start reaches home.
    h.settings.device_check_for_op = False
    await _start(h, ADMIN_ID)
    await _start(h, USER_ID, f"ref_{ADMIN_ID}")
    home = h.tg.last_text(USER_ID)
    assert "Подтвердите устройство" in home

    def last_user_markup():
        return [m for m in h.tg.sent(SendMessage) if m.chat_id == USER_ID][-1].reply_markup

    first_button = last_user_markup().inline_keyboard[0][0]
    assert first_button.web_app is not None and first_button.web_app.url == "https://mini.example/verify"

    # Referral activity threshold is reached, but the bonus waits for the device check.
    await h.feed(callback_update(USER_ID, "daily:claim"))
    assert await _balance(h, ADMIN_ID) == h.settings.signup_bonus

    await h.feed(callback_update(USER_ID, "menu:withdraw"))
    withdraw_markup = [m for m in h.tg.sent(EditMessageText) if m.chat_id == USER_ID][-1].reply_markup
    assert withdraw_markup.inline_keyboard[0][0].web_app is not None
    assert not any(
        b.callback_data and b.callback_data.startswith("wd:g:")
        for row in withdraw_markup.inline_keyboard
        for b in row
    )

    async with h.factory() as session:
        user = await session.get(User, USER_ID)
        await devices.register_device(
            session,
            user=user,
            fingerprint="e" * 64,
            ip="1.1.1.1",
            user_agent="ua",
            platform="android",
            tg_version="8.0",
            signals={},
            settings=h.settings,
        )
        await referrals.activate_if_ready(session, user=user, settings=h.settings)
        await session.commit()
    assert await _balance(h, ADMIN_ID) == h.settings.signup_bonus + h.settings.referral_l1_bonus

    await h.feed(message_update(USER_ID, "/menu"))
    assert "Подтвердите устройство" not in h.tg.last_text(USER_ID)
    assert last_user_markup().inline_keyboard[0][0].web_app is None

    # Admin sees the device line and can toggle trust.
    await h.feed(callback_update(ADMIN_ID, f"admin:u:{USER_ID}"))
    card = h.tg.last_text(ADMIN_ID)
    assert "Устройство: подтверждено" in card
    await h.feed(callback_update(ADMIN_ID, f"admin:u:{USER_ID}:trust:1"))
    assert "доверенный" in h.tg.last_text(ADMIN_ID)
    await h.feed(callback_update(ADMIN_ID, "admin:twinks"))
    assert "Твинки" in h.tg.last_text(ADMIN_ID)


@pytest.mark.asyncio
async def test_daily_claim_flow(harness: BotHarness) -> None:
    h = harness
    await _start(h, USER_ID)
    await h.feed(callback_update(USER_ID, "menu:daily"))
    assert "Ежедневная награда" in h.tg.last_text(USER_ID)
    await h.feed(callback_update(USER_ID, "daily:claim"))
    assert "+5" in h.tg.last_text(USER_ID)
    assert await _balance(h, USER_ID) == h.settings.signup_bonus + h.settings.daily_base_reward
    await h.feed(callback_update(USER_ID, "daily:claim"))
    assert "уже" in h.tg.alerts()[-1].lower()


@pytest.mark.asyncio
async def test_withdraw_flow_notifies_admin_and_user(harness: BotHarness, monkeypatch) -> None:
    h = harness
    await _start(h, ADMIN_ID)
    await _start(h, USER_ID)
    await h.feed(callback_update(USER_ID, "wd:g:g50"))
    assert "Недостаточно" in h.tg.last_text(USER_ID)

    async with h.factory() as session:
        await ledger.credit(session, user_id=USER_ID, amount=100, kind=LedgerKind.TASK)
        await session.commit()
    h.tg.clear()
    await h.feed(callback_update(USER_ID, "menu:withdraw"))
    assert "Доступно: <b>105" in h.tg.last_text(USER_ID)
    assert "Выберите готовый подарок" in h.tg.last_text(USER_ID)
    withdraw_markup = [m for m in h.tg.sent(EditMessageText) if m.chat_id == USER_ID][-1].reply_markup
    assert any(b.callback_data == "wd:g:g50" for row in withdraw_markup.inline_keyboard for b in row)
    await h.feed(callback_update(USER_ID, "wd:g:g50"))
    assert "Заявка #1" in h.tg.last_text(USER_ID)
    assert await _balance(h, USER_ID) == 55
    admin_alert = h.tg.last_text(ADMIN_ID)
    assert "Новая заявка на вывод #1" in admin_alert
    assert "🎁" in admin_alert
    alert_markup = [r for r in h.tg.sent(SendMessage) if r.chat_id == ADMIN_ID][-1].reply_markup
    assert alert_markup.inline_keyboard[0][0].callback_data == "admin:wd:ok:1"

    # Admin approves, then sends Stars via Fragment (mocked). User is notified on each step.
    await h.feed(callback_update(ADMIN_ID, "admin:wd:ok:1"))
    assert "согласована" in h.tg.last_text(USER_ID)

    async def _fake_buy(settings, *, username: str, amount: int):
        return FragmentPurchase(username=username or "user", amount=amount, raw={})

    monkeypatch.setattr("app.services.fragment.buy_stars", _fake_buy)
    await h.feed(callback_update(ADMIN_ID, "admin:wd:fragment:1"))
    assert "отправлен" in h.tg.last_text(USER_ID) or any(
        "Отправлено" in a for a in h.tg.alerts()
    )
    async with h.factory() as session:
        wd = await session.get(Withdrawal, 1)
        assert wd.status == WithdrawalStatus.SENT.value
        assert wd.gift_id == "g50"
    assert await _balance(h, USER_ID) == 55

    # A second request can be cancelled by the user and Stars come back.
    await h.feed(callback_update(USER_ID, "wd:g:g50"))
    assert await _balance(h, USER_ID) == 5
    await h.feed(callback_update(USER_ID, "wd:list"))
    await h.feed(callback_update(USER_ID, "wd:cancel:2"))
    assert await _balance(h, USER_ID) == 55
    assert any("отменена пользователем" in text for text in h.tg.texts(ADMIN_ID))


@pytest.mark.asyncio
async def test_withdraw_gift_reject_with_reason(harness: BotHarness) -> None:
    h = harness
    await _start(h, ADMIN_ID)
    await _start(h, USER_ID)
    async with h.factory() as session:
        await ledger.credit(session, user_id=USER_ID, amount=200, kind=LedgerKind.TASK)
        await session.commit()
    await h.feed(callback_update(USER_ID, "wd:g:g100"))
    assert "Заявка #1" in h.tg.last_text(USER_ID)
    assert await _balance(h, USER_ID) == 105

    await h.feed(callback_update(ADMIN_ID, "admin:wd:no:1"))
    assert "Причина отклонения" in h.tg.last_text(ADMIN_ID)
    await h.feed(message_update(ADMIN_ID, "Подозрение на накрутку"))
    assert await _balance(h, USER_ID) == 205
    user_note = h.tg.last_text(USER_ID)
    assert "отклонена" in user_note and "накрутку" in user_note


@pytest.mark.asyncio
async def test_admin_panel_access_and_stats(harness: BotHarness) -> None:
    h = harness
    await _start(h, USER_ID)
    await h.feed(message_update(USER_ID, "/admin"))
    assert "Я понимаю только кнопки" in h.tg.last_text(USER_ID)
    await h.feed(callback_update(USER_ID, "admin:home"))
    assert "Недостаточно прав" in h.tg.alerts()[-1]

    await _start(h, ADMIN_ID)
    await h.feed(message_update(ADMIN_ID, "/admin"))
    assert "Админка" in h.tg.last_text(ADMIN_ID) or "Админ" in h.tg.last_text(ADMIN_ID)
    await h.feed(callback_update(ADMIN_ID, "admin:stats"))
    stats_text = h.tg.last_text(ADMIN_ID)
    assert "Статистика" in stats_text
    assert "Пользователи: <b>2</b>" in stats_text
    assert "Баланс Stars бота: <b>321</b>" in stats_text
    await h.feed(callback_update(ADMIN_ID, "admin:reconcile"))
    assert "Расхождений" in h.tg.last_text(ADMIN_ID)


@pytest.mark.asyncio
async def test_admin_user_card_adjust_and_ban(harness: BotHarness) -> None:
    h = harness
    await _start(h, ADMIN_ID)
    await _start(h, USER_ID)
    await h.feed(callback_update(ADMIN_ID, "admin:users"))
    await h.feed(message_update(ADMIN_ID, f"@user{USER_ID}"))
    card = h.tg.last_text(ADMIN_ID)
    assert f"<code>{USER_ID}</code>" in card and "Баланс: <b>5" in card

    await h.feed(callback_update(ADMIN_ID, f"admin:u:{USER_ID}:adj"))
    await h.feed(message_update(ADMIN_ID, "+40 бонус за конкурс"))
    assert await _balance(h, USER_ID) == 45
    assert "начислил <b>40" in h.tg.last_text(USER_ID)
    assert "Баланс: <b>45" in h.tg.last_text(ADMIN_ID)

    await h.feed(callback_update(ADMIN_ID, f"admin:u:{USER_ID}:ban"))
    await h.feed(message_update(ADMIN_ID, "мультиаккаунт"))
    assert "БАН" in h.tg.last_text(ADMIN_ID)
    await h.feed(callback_update(USER_ID, "menu:daily"))
    assert "Доступ закрыт" in h.tg.alerts()[-1]
    await h.feed(message_update(USER_ID, "/start"))
    assert "мультиаккаунт" in h.tg.last_text(USER_ID)

    await h.feed(callback_update(ADMIN_ID, f"admin:u:{USER_ID}:unban"))
    assert "активен" in h.tg.last_text(ADMIN_ID)
    await h.feed(callback_update(ADMIN_ID, "admin:audit:0"))
    audit_text = h.tg.last_text(ADMIN_ID)
    assert "Разбан" in audit_text and "Корректировка баланса" in audit_text


@pytest.mark.asyncio
async def test_runtime_settings_and_maintenance(harness: BotHarness) -> None:
    h = harness
    await _start(h, ADMIN_ID)
    await _start(h, USER_ID)
    await h.feed(callback_update(ADMIN_ID, "admin:set:withdraw_min"))
    assert "withdraw_min" in h.tg.last_text(ADMIN_ID)
    await h.feed(message_update(ADMIN_ID, "abc"))
    assert "⚠️" in h.tg.last_text(ADMIN_ID)
    await h.feed(message_update(ADMIN_ID, "20"))
    assert "Сохранено" in h.tg.last_text(ADMIN_ID)
    await h.feed(callback_update(USER_ID, "menu:withdraw"))
    assert "Минимум: 20" in h.tg.last_text(USER_ID)

    await h.feed(callback_update(ADMIN_ID, "admin:set:maintenance_mode:on"))
    await h.feed(callback_update(USER_ID, "menu:daily"))
    from app.bot import brand

    expanded = brand.expand(h.settings.maintenance_text) or h.settings.maintenance_text
    assert expanded[:20] in h.tg.alerts()[-1]
    await h.feed(message_update(USER_ID, "/menu"))
    assert h.tg.last_text(USER_ID) == expanded
    await h.feed(message_update(ADMIN_ID, "/menu"))
    assert "KodoStars" in h.tg.last_text(ADMIN_ID)
    await h.feed(callback_update(ADMIN_ID, "admin:set:maintenance_mode:reset"))
    await h.feed(message_update(USER_ID, "/menu"))
    assert "KodoStars" in h.tg.last_text(USER_ID)


@pytest.mark.asyncio
async def test_payment_flow_is_idempotent_and_refundable(harness: BotHarness) -> None:
    h = harness
    await _start(h, ADMIN_ID)
    await _start(h, USER_ID)
    await h.feed(callback_update(USER_ID, "menu:boosts"))
    await h.feed(callback_update(USER_ID, "boost:view:1"))
    await h.feed(callback_update(USER_ID, "boost:buy:1"))
    invoice = h.tg.sent(SendInvoice)[-1]
    assert invoice.currency == "XTR" and invoice.payload == f"boost:1:{USER_ID}"

    await h.feed(pre_checkout_update(USER_ID, invoice.payload, invoice.prices[0].amount))
    assert h.tg.sent(AnswerPreCheckoutQuery)[-1].ok is True
    await h.feed(pre_checkout_update(USER_ID, invoice.payload, 1))
    assert h.tg.sent(AnswerPreCheckoutQuery)[-1].ok is False

    await h.feed(successful_payment_update(USER_ID, invoice.payload, invoice.prices[0].amount, "chg_1"))
    user_texts = h.tg.texts(USER_ID)
    assert any("Оплата прошла" in text for text in user_texts)
    # The seeded "Первый буст" task auto-completes and the user is told about it.
    assert any("Первый буст" in text and "+10" in text for text in user_texts)
    before = await _balance(h, USER_ID)
    assert before == 5 + 25 + 10
    await h.feed(successful_payment_update(USER_ID, invoice.payload, invoice.prices[0].amount, "chg_1"))
    assert await _balance(h, USER_ID) == before

    await h.feed(callback_update(ADMIN_ID, "admin:pay:0"))
    assert "Выручка (без возвратов): <b>15 XTR</b>" in h.tg.last_text(ADMIN_ID)
    await h.feed(callback_update(ADMIN_ID, "admin:pay:refund:1"))
    assert "Вернуть" in h.tg.last_text(ADMIN_ID)
    await h.feed(callback_update(ADMIN_ID, "admin:pay:refund:1:yes"))
    assert await _balance(h, USER_ID) == before - 25
    assert "возвращена" in h.tg.last_text(USER_ID)
    async with h.factory() as session:
        payment = await payments.get_by_charge(session, "chg_1")
        assert payment.status == "refunded"


@pytest.mark.asyncio
async def test_promo_redeem_via_menu(harness: BotHarness) -> None:
    h = harness
    await _start(h, USER_ID)
    async with h.factory() as session:
        await promo.create_promo(session, code="HELLO", reward=12, max_uses=1)
        await session.commit()
    await h.feed(callback_update(USER_ID, "menu:promo"))
    assert "промокод" in h.tg.last_text(USER_ID).lower()
    await h.feed(message_update(USER_ID, "nope"))
    assert "⚠️" in h.tg.last_text(USER_ID)
    await h.feed(message_update(USER_ID, "hello"))
    assert "+12" in h.tg.last_text(USER_ID)
    assert await _balance(h, USER_ID) == 17


@pytest.mark.asyncio
async def test_task_subscribe_check_and_catalog_management(harness: BotHarness) -> None:
    h = harness
    await _start(h, ADMIN_ID)
    await _start(h, USER_ID)
    # Admin creates a subscribe task through the wizard.
    await h.feed(callback_update(ADMIN_ID, "admin:task:new"))
    await h.feed(callback_update(ADMIN_ID, "admin:task:new:subscribe"))
    await h.feed(message_update(ADMIN_ID, "Наш канал"))
    await h.feed(message_update(ADMIN_ID, "-"))
    await h.feed(message_update(ADMIN_ID, "30"))
    await h.feed(message_update(ADMIN_ID, "@news"))
    card = h.tg.last_text(ADMIN_ID)
    assert "Наш канал" in card and "@news" in card

    await h.feed(callback_update(USER_ID, "menu:tasks"))
    tasks_markup = h.tg.sent()[-1].reply_markup
    task_button = next(b for row in tasks_markup.inline_keyboard for b in row if "Наш канал" in b.text)
    task_id = int(task_button.callback_data.split(":")[-1])

    h.tg.member_status[("@news", USER_ID)] = "left"
    await h.feed(callback_update(USER_ID, f"task:do:{task_id}"))
    assert "Подписка ещё не найдена" in h.tg.alerts()[-1]
    h.tg.member_status[("@news", USER_ID)] = "member"
    await h.feed(callback_update(USER_ID, f"task:do:{task_id}"))
    assert "+30" in h.tg.alerts()[-1]
    assert await _balance(h, USER_ID) == 35
    await h.feed(callback_update(USER_ID, f"task:do:{task_id}"))
    assert "уже выполнено" in h.tg.alerts()[-1]


@pytest.mark.asyncio
async def test_broadcast_wizard_runs_in_background(harness: BotHarness) -> None:
    h = harness
    await _start(h, ADMIN_ID)
    await _start(h, USER_ID)
    await _start(h, OTHER_ID)
    await h.feed(callback_update(ADMIN_ID, "admin:bc"))
    await h.feed(callback_update(ADMIN_ID, "admin:bc:new"))
    await h.feed(message_update(ADMIN_ID, "Всем привет!", message_id=555))
    assert "кнопку" in h.tg.last_text(ADMIN_ID).lower()
    await h.feed(message_update(ADMIN_ID, "Канал | https://t.me/kodo"))
    assert "Кому отправить" in h.tg.last_text(ADMIN_ID)
    await h.feed(callback_update(ADMIN_ID, "admin:bc:aud:all"))
    confirm = h.tg.last_text(ADMIN_ID)
    assert "3 чел" in confirm and "Кнопка: «Канал»" in confirm
    preview_copies = len(h.tg.sent(CopyMessage))
    await h.feed(callback_update(ADMIN_ID, "admin:bc:test"))
    assert len(h.tg.sent(CopyMessage)) == preview_copies + 1

    await h.feed(callback_update(ADMIN_ID, "admin:bc:go"))
    for _ in range(50):
        await asyncio.sleep(0.02)
        if not h.runner.is_running(1):
            break
    async with h.factory() as session:
        row = await session.get(Broadcast, 1)
        assert row.status == BroadcastStatus.DONE.value
        assert (row.total, row.sent, row.failed) == (3, 3, 0)
    copies = [c for c in h.tg.sent(CopyMessage) if c.message_id == 555 and c.reply_markup is not None]
    assert {c.chat_id for c in copies} >= {USER_ID, OTHER_ID, ADMIN_ID}
    assert any("100%" in text for text in h.tg.texts(ADMIN_ID))


@pytest.mark.asyncio
async def test_export_sends_document(harness: BotHarness) -> None:
    h = harness
    await _start(h, ADMIN_ID)
    await h.feed(callback_update(ADMIN_ID, "admin:exp:users"))
    document = h.tg.sent(SendDocument)[-1]
    assert document.document.filename.startswith("kodostars_users_")


@pytest.mark.asyncio
async def test_admin_piarflow_toggle(harness: BotHarness) -> None:
    h = harness
    await _start(h, ADMIN_ID)
    await h.feed(callback_update(ADMIN_ID, "admin:prov"))
    assert "PiarFlow" in h.tg.last_text(ADMIN_ID)
    await h.feed(callback_update(ADMIN_ID, "admin:prov:tg:piarflow"))
    assert "ВЫКЛ" in h.tg.last_text(ADMIN_ID) or "ВКЛ" in h.tg.last_text(ADMIN_ID)


@pytest.mark.asyncio
async def test_owner_manages_admins(harness: BotHarness) -> None:
    h = harness
    await _start(h, ADMIN_ID)
    await _start(h, USER_ID)
    await h.feed(callback_update(ADMIN_ID, "admin:adm"))
    assert "Администраторы" in h.tg.last_text(ADMIN_ID)
    await h.feed(callback_update(ADMIN_ID, "admin:adm:add"))
    await h.feed(message_update(ADMIN_ID, str(OTHER_ID)))
    assert "не запускал бота" in h.tg.last_text(ADMIN_ID)
    await h.feed(message_update(ADMIN_ID, str(USER_ID)))
    assert h.access.is_admin(USER_ID)
    await h.feed(message_update(USER_ID, "/admin"))
    assert "Админка" in h.tg.last_text(USER_ID)
    # A DB admin cannot add other admins.
    await h.feed(callback_update(USER_ID, "admin:adm:add"))
    assert "Недостаточно прав" in h.tg.alerts()[-1]
    await h.feed(callback_update(ADMIN_ID, f"admin:adm:del:{USER_ID}"))
    assert not h.access.is_admin(USER_ID)
