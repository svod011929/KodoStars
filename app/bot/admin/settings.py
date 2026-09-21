"""Runtime settings and PiarFlow provider toggle."""

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.admin import keyboards as kb
from app.bot.admin import texts
from app.bot.admin.states import AdminFSM
from app.bot.utils import safe_answer, safe_edit
from app.config import RUNTIME_OVERRIDABLE, Settings
from app.op.gate import CASCADE, enabled_providers, provider_configured, toggle_provider
from app.services import audit
from app.services.app_settings import RuntimeSettingsStore
from app.services.errors import EconomyError

router = Router(name="admin.settings")

# Telegram accepts exactly 30 days for paid subscription invite links.


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
