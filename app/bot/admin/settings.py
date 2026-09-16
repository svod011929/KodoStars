"""Runtime settings, OP providers and manual OP channels."""

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, MessageOriginChannel
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.admin import keyboards as kb
from app.bot.admin import texts
from app.bot.admin.states import AdminFSM
from app.bot.utils import parse_id, safe_answer, safe_edit
from app.config import RUNTIME_OVERRIDABLE, Settings
from app.op.gate import CASCADE, enabled_providers, provider_configured, toggle_provider
from app.op.manual import chat_ref, format_channel_entry, validate_channel_entry
from app.services import audit
from app.services.app_settings import RuntimeSettingsStore
from app.services.errors import EconomyError

router = Router(name="admin.settings")

# Telegram accepts exactly 30 days for paid subscription invite links.
SUBSCRIPTION_PERIOD_SEC = 30 * 24 * 3600


# --- runtime settings ---------------------------------------------------------------


async def _settings_view(session: AsyncSession, store: RuntimeSettingsStore):
    effective = await store.effective(session)
    overrides = await store.overrides(session)
    return texts.settings_home(effective, overrides), kb.settings_home()


@router.callback_query(F.data == "admin:set")
async def settings_home(
    call: CallbackQuery, session: AsyncSession, state: FSMContext, settings_store: RuntimeSettingsStore
) -> None:
    await state.clear()
    text, markup = await _settings_view(session, settings_store)
    await safe_answer(call)
    await safe_edit(call.message, text, markup)


async def _setting_view(session: AsyncSession, store: RuntimeSettingsStore, key: str):
    effective = await store.effective(session)
    overrides = await store.overrides(session)
    overridden = key in overrides
    text = texts.setting_prompt(key, getattr(effective, key), store.default_value(key), overridden)
    return text, kb.setting_edit(key, overridden, RUNTIME_OVERRIDABLE[key] is bool)


@router.callback_query(F.data.regexp(r"^admin:set:(\w+)$"))
async def setting_open(
    call: CallbackQuery, session: AsyncSession, state: FSMContext, settings_store: RuntimeSettingsStore
) -> None:
    key = (call.data or "").split(":")[-1]
    if key not in RUNTIME_OVERRIDABLE:
        await safe_answer(call, "Неизвестная настройка", alert=True)
        return
    await state.set_state(AdminFSM.setting_value)
    await state.set_data({"key": key})
    text, markup = await _setting_view(session, settings_store, key)
    await safe_answer(call)
    await safe_edit(call.message, text, markup)


async def _apply_setting(
    session: AsyncSession, store: RuntimeSettingsStore, key: str, raw: str, admin_id: int
) -> None:
    value = await store.set(session, key=key, raw=raw, admin_id=admin_id)
    await audit.log_action(
        session, admin_id=admin_id, action="settings.set", target_type="setting", target_id=key, value=value
    )


@router.callback_query(F.data.regexp(r"^admin:set:(\w+):(on|off|reset)$"))
async def setting_quick(
    call: CallbackQuery, session: AsyncSession, settings_store: RuntimeSettingsStore
) -> None:
    parts = (call.data or "").split(":")
    key, action = parts[2], parts[3]
    if key not in RUNTIME_OVERRIDABLE:
        await safe_answer(call, "Неизвестная настройка", alert=True)
        return
    try:
        if action == "reset":
            await settings_store.reset(session, key=key)
            await audit.log_action(
                session,
                admin_id=call.from_user.id,
                action="settings.reset",
                target_type="setting",
                target_id=key,
            )
        else:
            await _apply_setting(
                session, settings_store, key, "true" if action == "on" else "false", call.from_user.id
            )
    except EconomyError as exc:
        await safe_answer(call, exc.message, alert=True)
        return
    text, markup = await _setting_view(session, settings_store, key)
    await safe_answer(call, "Сохранено")
    await safe_edit(call.message, text, markup)


@router.message(StateFilter(AdminFSM.setting_value), F.text)
async def setting_set(
    message: Message, session: AsyncSession, state: FSMContext, settings_store: RuntimeSettingsStore
) -> None:
    key = (await state.get_data()).get("key")
    if key not in RUNTIME_OVERRIDABLE:
        await state.clear()
        await message.answer("Настройка не выбрана.")
        return
    try:
        await _apply_setting(session, settings_store, key, message.text or "", message.from_user.id)
    except EconomyError as exc:
        await message.answer(f"⚠️ {exc.message}")
        return
    text, markup = await _setting_view(session, settings_store, key)
    await message.answer("Сохранено ✅\n\n" + text, reply_markup=markup)


# --- providers ----------------------------------------------------------------------


@router.callback_query(F.data == "admin:prov")
async def providers_home(call: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    enabled = await enabled_providers(session, settings)
    states = {name: name in enabled for name in CASCADE}
    configured = {name: provider_configured(name, settings) for name in CASCADE}
    await safe_answer(call)
    await safe_edit(call.message, texts.providers_home(states, configured), kb.providers(states))


@router.callback_query(F.data.startswith("admin:prov:tg:"))
async def providers_toggle(call: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    name = (call.data or "").split(":")[-1]
    row = await toggle_provider(session, name, admin_id=call.from_user.id)
    if row is None:
        await safe_answer(call, "Неизвестный провайдер", alert=True)
        return
    await audit.log_action(
        session,
        admin_id=call.from_user.id,
        action="provider.toggle",
        target_type="provider",
        target_id=name,
        enabled=row.enabled,
    )
    enabled = await enabled_providers(session, settings)
    states = {item: item in enabled for item in CASCADE}
    configured = {item: provider_configured(item, settings) for item in CASCADE}
    await safe_answer(call, f"{name}: {'ВКЛ' if row.enabled else 'ВЫКЛ'}")
    await safe_edit(call.message, texts.providers_home(states, configured), kb.providers(states))


# --- manual channels ----------------------------------------------------------------


async def _channel_checks(bot: Bot, channels: list[str]) -> dict[str, str]:
    me = await bot.get_me()
    checks: dict[str, str] = {}
    for channel in channels:
        try:
            member = await bot.get_chat_member(chat_id=chat_ref(channel), user_id=me.id)
            checks[channel] = (
                "✅ бот админ" if member.status in {"administrator", "creator"} else "⚠️ бот не админ"
            )
        except TelegramAPIError as exc:
            checks[channel] = f"❌ {str(exc).split(':')[-1].strip()[:40]}"
    return checks


async def _store_channels(
    session: AsyncSession,
    store: RuntimeSettingsStore,
    *,
    add: list[str],
    admin_id: int,
) -> None:
    effective = await store.effective(session)
    current = effective.parse_channel_list(effective.manual_op_channels)
    merged = list(dict.fromkeys(current + add))
    await store.set(session, key="manual_op_channels", raw=",".join(merged), admin_id=admin_id)
    await audit.log_action(
        session, admin_id=admin_id, action="channel.add", target_type="channel", target_id=",".join(add)
    )


async def _finish_add(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
    store: RuntimeSettingsStore,
    bot: Bot,
    entries: list[str],
) -> None:
    await _store_channels(session, store, add=entries, admin_id=message.from_user.id)
    await state.clear()
    text, markup = await _channels_view(session, store, bot)
    await message.answer("\n".join(texts.channel_added(entry) for entry in entries))
    await message.answer(text, reply_markup=markup)


async def _channels_view(session: AsyncSession, store: RuntimeSettingsStore, bot: Bot):
    effective = await store.effective(session)
    channels = effective.parse_channel_list(effective.manual_op_channels)
    checks = await _channel_checks(bot, channels)
    return texts.channels_home(channels, checks), kb.channels(channels)


@router.callback_query(F.data == "admin:ch")
async def channels_home(
    call: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
    settings_store: RuntimeSettingsStore,
    bot: Bot,
) -> None:
    await state.clear()
    text, markup = await _channels_view(session, settings_store, bot)
    await safe_answer(call)
    await safe_edit(call.message, text, markup)


@router.callback_query(F.data == "admin:ch:add")
async def channel_add_start(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminFSM.channel_add)
    await safe_answer(call)
    await safe_edit(call.message, texts.channel_add_prompt(), kb.cancel_to("admin:ch"))


@router.message(StateFilter(AdminFSM.channel_add), F.forward_origin)
async def channel_add_forward(
    message: Message, session: AsyncSession, state: FSMContext, settings_store: RuntimeSettingsStore, bot: Bot
) -> None:
    origin = message.forward_origin
    if not isinstance(origin, MessageOriginChannel):
        await message.answer("Перешлите пост именно из канала.", reply_markup=kb.cancel_to("admin:ch"))
        return
    chat = origin.chat
    title = chat.title or str(chat.id)
    if chat.username:
        entry = format_channel_entry(f"@{chat.username}", None, title)
        await _finish_add(message, session, state, settings_store, bot, [entry])
        return
    await state.set_state(AdminFSM.channel_link)
    await state.update_data(pending_chat_id=chat.id, pending_title=title)
    await message.answer(texts.channel_link_prompt(title, chat.id), reply_markup=kb.cancel_to("admin:ch"))


@router.message(StateFilter(AdminFSM.channel_add), F.text)
async def channel_add(
    message: Message, session: AsyncSession, state: FSMContext, settings_store: RuntimeSettingsStore, bot: Bot
) -> None:
    new_items = [part.strip() for part in (message.text or "").split(",") if part.strip()]
    if not new_items:
        await message.answer(texts.channel_add_prompt(), reply_markup=kb.cancel_to("admin:ch"))
        return
    for item in new_items:
        problem = validate_channel_entry(item)
        if problem:
            await message.answer(f"⚠️ {problem}", reply_markup=kb.cancel_to("admin:ch"))
            return
    await _finish_add(message, session, state, settings_store, bot, new_items)


@router.message(StateFilter(AdminFSM.channel_link), F.text)
async def channel_add_link(
    message: Message, session: AsyncSession, state: FSMContext, settings_store: RuntimeSettingsStore, bot: Bot
) -> None:
    data = await state.get_data()
    chat_id = data.get("pending_chat_id")
    title = str(data.get("pending_title") or chat_id)
    if chat_id is None:
        await state.set_state(AdminFSM.channel_add)
        await message.answer(texts.channel_add_prompt(), reply_markup=kb.cancel_to("admin:ch"))
        return
    raw = (message.text or "").strip()
    if raw.lower().startswith("auto"):
        parts = raw.split()
        price = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        try:
            if price > 0:
                link = await bot.create_chat_subscription_invite_link(
                    chat_id=chat_id,
                    subscription_period=SUBSCRIPTION_PERIOD_SEC,
                    subscription_price=price,
                    name="KodoStars OP",
                )
            else:
                link = await bot.create_chat_invite_link(chat_id=chat_id, name="KodoStars OP")
        except TelegramAPIError as exc:
            await message.answer(
                f"Не удалось создать ссылку: {exc}\nПришлите ссылку вручную.",
                reply_markup=kb.cancel_to("admin:ch"),
            )
            return
        url = link.invite_link
    elif raw.startswith(("https://t.me/", "http://t.me/", "tg://")):
        url = raw
    else:
        await message.answer(
            texts.channel_link_prompt(title, int(chat_id), paid_hint=False),
            reply_markup=kb.cancel_to("admin:ch"),
        )
        return
    entry = format_channel_entry(chat_id, url, title)
    await _finish_add(message, session, state, settings_store, bot, [entry])


@router.callback_query(F.data.regexp(r"^admin:ch:del:(\d+)$"))
async def channel_delete(
    call: CallbackQuery, session: AsyncSession, settings_store: RuntimeSettingsStore, bot: Bot
) -> None:
    index = parse_id(call.data)
    effective = await settings_store.effective(session)
    channels = effective.parse_channel_list(effective.manual_op_channels)
    if index >= len(channels):
        await safe_answer(call, "Канал не найден", alert=True)
        return
    removed = channels.pop(index)
    await settings_store.set(
        session, key="manual_op_channels", raw=",".join(channels), admin_id=call.from_user.id
    )
    await audit.log_action(
        session, admin_id=call.from_user.id, action="channel.remove", target_type="channel", target_id=removed
    )
    text, markup = await _channels_view(session, settings_store, bot)
    await safe_answer(call, f"Удалён {removed}")
    await safe_edit(call.message, text, markup)
