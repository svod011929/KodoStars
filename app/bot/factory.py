from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.handlers import register_handlers
from app.bot.middlewares.context import LoggingContextMiddleware
from app.bot.middlewares.db import DbSessionMiddleware
from app.bot.middlewares.op_gate import OpGateMiddleware
from app.bot.middlewares.runtime import RuntimeMiddleware
from app.bot.middlewares.throttle import ThrottleMiddleware
from app.bot.middlewares.user import UserMiddleware
from app.bot.middlewares.user_lock import UserLockMiddleware
from app.bot.notify import Notifier
from app.bot.request_middleware import install_request_middlewares
from app.bot.utils import markup, url_button
from app.config import Settings
from app.db.models import Broadcast
from app.op.gate import OpGate
from app.services.access import AccessRegistry
from app.services.app_settings import RuntimeSettingsStore
from app.services.broadcasts import BroadcastRunner, Sender


def create_bot(settings: Settings) -> Bot:
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )
    return install_request_middlewares(bot)


def make_broadcast_sender(bot: Bot) -> Sender:
    async def send(chat_id: int, broadcast: Broadcast) -> None:
        reply_markup = None
        if broadcast.button_text and broadcast.button_url:
            reply_markup = markup([url_button(broadcast.button_text, broadcast.button_url)])
        await bot.copy_message(
            chat_id=chat_id,
            from_chat_id=broadcast.from_chat_id,
            message_id=broadcast.message_id,
            reply_markup=reply_markup,
        )

    return send


def create_dispatcher(
    settings: Settings,
    session_factory: async_sessionmaker,
    op_gate: OpGate,
    *,
    access: AccessRegistry,
    settings_store: RuntimeSettingsStore,
    notifier: Notifier | None,
    broadcast_runner: BroadcastRunner,
    bot_username: str,
) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.outer_middleware(LoggingContextMiddleware())
    dp.update.outer_middleware(ThrottleMiddleware(settings.throttle_seconds))
    # Must wrap the DB session: one user → one transaction at a time.
    dp.update.outer_middleware(UserLockMiddleware())
    dp.update.outer_middleware(
        DbSessionMiddleware(session_factory, dispatcher=notifier.dispatch if notifier else None)
    )
    dp.update.outer_middleware(RuntimeMiddleware(settings_store, access))
    dp.update.outer_middleware(UserMiddleware(settings))
    dp.update.outer_middleware(OpGateMiddleware(settings, op_gate))
    dp.workflow_data.update(
        settings=settings,
        op_gate=op_gate,
        access=access,
        settings_store=settings_store,
        broadcast_runner=broadcast_runner,
        bot_username=bot_username,
    )
    register_handlers(dp)
    return dp
