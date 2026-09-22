from aiogram import Router

from app.bot.admin import (
    admins,
    broadcast,
    catalog,
    data,
    home,
    payments,
    piarflow,
    promo,
    settings,
    users,
    withdrawals,
)
from app.bot.filters import IsAdmin


def build_admin_router() -> Router:
    router = Router(name="admin")
    router.message.filter(IsAdmin())
    router.callback_query.filter(IsAdmin())
    for module in (
        home,
        users,
        withdrawals,
        broadcast,
        catalog,
        promo,
        payments,
        settings,
        piarflow,
        admins,
        data,
    ):
        router.include_router(module.router)
    return router
