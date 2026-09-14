from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.handlers import register_handlers
from app.bot.middlewares.db import DbSessionMiddleware
from app.bot.middlewares.op_gate import OpGateMiddleware
from app.bot.middlewares.user import UserMiddleware
from app.config import Settings
from app.op.gate import OpGate


def create_bot(settings: Settings) -> Bot:
    return Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher(
    settings: Settings,
    session_factory: async_sessionmaker,
    op_gate: OpGate,
) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.outer_middleware(DbSessionMiddleware(session_factory))
    dp.update.outer_middleware(UserMiddleware(settings))
    dp.update.outer_middleware(OpGateMiddleware(settings, op_gate))
    dp.workflow_data.update(settings=settings, op_gate=op_gate)
    register_handlers(dp)
    return dp
