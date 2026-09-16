import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

log = structlog.get_logger("kodostars.commands")

USER_COMMANDS = [
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="menu", description="Открыть меню"),
    BotCommand(command="profile", description="Профиль и баланс"),
    BotCommand(command="help", description="Как это работает"),
    BotCommand(command="paysupport", description="Поддержка по оплате"),
]

ADMIN_COMMANDS = [
    *USER_COMMANDS,
    BotCommand(command="admin", description="Панель администратора"),
]


async def setup_commands(bot: Bot, admin_ids: frozenset[int]) -> None:
    try:
        await bot.set_my_commands(USER_COMMANDS, scope=BotCommandScopeDefault())
    except TelegramAPIError as exc:
        log.warning("set_my_commands_failed", error=str(exc))
        return
    for admin_id in admin_ids:
        try:
            await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=admin_id))
        except TelegramAPIError as exc:
            log.info("set_admin_commands_failed", admin_id=admin_id, error=str(exc))
