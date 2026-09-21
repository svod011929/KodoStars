"""aiogram request middleware: commit pending DB work before every Telegram API call,
and rewrite message HTML to use premium ``<tg-emoji>`` tags.
"""

from __future__ import annotations

from aiogram import Bot
from aiogram.client.session.middlewares.base import BaseRequestMiddleware, NextRequestMiddlewareType
from aiogram.methods import EditMessageCaption, EditMessageText, Response, SendMessage, TelegramMethod
from aiogram.methods.base import TelegramType

from app.bot import emoji as pe
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


class PremiumEmojiRequestMiddleware(BaseRequestMiddleware):
    """Convert known unicode emoji in outgoing message HTML to ``<tg-emoji>``."""

    async def __call__(
        self,
        make_request: NextRequestMiddlewareType[TelegramType],
        bot: Bot,
        method: TelegramMethod[TelegramType],
    ) -> Response[TelegramType]:
        if isinstance(method, (SendMessage, EditMessageText)) and method.text:
            method.text = pe.premiumize(method.text)
        elif isinstance(method, EditMessageCaption) and method.caption:
            method.caption = pe.premiumize(method.caption)
        return await make_request(bot, method)


def install_request_middlewares(bot: Bot) -> Bot:
    bot.session.middleware(PremiumEmojiRequestMiddleware())
    bot.session.middleware(CommitBeforeRequestMiddleware())
    return bot
