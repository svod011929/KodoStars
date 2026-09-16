"""aiogram request middleware: commit pending DB work before every Telegram API call."""

from __future__ import annotations

from aiogram import Bot
from aiogram.client.session.middlewares.base import BaseRequestMiddleware, NextRequestMiddlewareType
from aiogram.methods import Response, TelegramMethod
from aiogram.methods.base import TelegramType

from app.db.txn import commit_before_io


class CommitBeforeRequestMiddleware(BaseRequestMiddleware):
    async def __call__(
        self,
        make_request: NextRequestMiddlewareType[TelegramType],
        bot: Bot,
        method: TelegramMethod[TelegramType],
    ) -> Response[TelegramType]:
        await commit_before_io()
        return await make_request(bot, method)


def install_request_middlewares(bot: Bot) -> Bot:
    bot.session.middleware(CommitBeforeRequestMiddleware())
    return bot
