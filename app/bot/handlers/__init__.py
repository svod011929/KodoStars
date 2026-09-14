from aiogram import Dispatcher

from app.bot.handlers import admin, cabinet, earn, payments, start, withdraw


def register_handlers(dp: Dispatcher) -> None:
    dp.include_router(start.router)
    dp.include_router(cabinet.router)
    dp.include_router(earn.router)
    dp.include_router(withdraw.router)
    dp.include_router(payments.router)
    dp.include_router(admin.router)
