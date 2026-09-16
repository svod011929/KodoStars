from aiogram import Dispatcher

from app.bot.admin.router import build_admin_router
from app.bot.errors import router as errors_router
from app.bot.handlers import cabinet, commands, earn, payments, promo, start, system, withdraw


def register_handlers(dp: Dispatcher) -> None:
    dp.include_router(errors_router)
    dp.include_router(start.router)
    dp.include_router(commands.router)
    dp.include_router(build_admin_router())
    dp.include_router(cabinet.router)
    dp.include_router(earn.router)
    dp.include_router(withdraw.router)
    dp.include_router(promo.router)
    dp.include_router(payments.router)
    dp.include_router(system.router)
