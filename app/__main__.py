from __future__ import annotations

import asyncio

import structlog
from aiogram.exceptions import TelegramUnauthorizedError

from app.bot.factory import create_bot, create_dispatcher
from app.config import get_settings
from app.db.seed import seed_catalog
from app.db.session import create_engine, create_session_factory, init_db
from app.logging import setup_logging
from app.op.gate import OpGate


async def run() -> None:
    settings = get_settings()
    setup_logging(settings)
    log = structlog.get_logger("kodostars")

    engine = create_engine(settings)
    await init_db(engine)
    session_factory = create_session_factory(engine)
    async with session_factory() as session:
        await seed_catalog(session)

    op_gate = OpGate(settings)
    bot = create_bot(settings)
    dp = create_dispatcher(settings, session_factory, op_gate)

    log.info(
        "starting_polling",
        placeholder_token=settings.is_placeholder_token,
        admins=len(settings.admin_ids),
        database=settings.database_url,
    )
    if settings.is_placeholder_token:
        log.warning(
            "bot_token_is_placeholder",
            hint="Задайте BOT_TOKEN в .env. Polling всё равно запускается.",
        )
    try:
        await dp.start_polling(bot)
    except TelegramUnauthorizedError:
        log.error("telegram_unauthorized", placeholder_token=settings.is_placeholder_token)
        if settings.is_placeholder_token:
            log.warning(
                "idle_after_placeholder_token",
                hint="Процесс остаётся запущенным. Подставьте настоящий BOT_TOKEN и перезапустите.",
            )
            await asyncio.Event().wait()
        else:
            raise
    finally:
        await bot.session.close()
        await engine.dispose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
