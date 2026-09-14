from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from app.config import Settings
from app.op.base import OpContext, OpResult, Sponsor

_SUBSCRIBED = {"creator", "administrator", "member", "restricted"}


class ManualAdapter:
    """Last-resort OP: getChatMember for MANUAL_OP_CHANNELS (@name or -100id)."""

    name = "manual"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _channels(self) -> list[str]:
        return self._settings.parse_channel_list(self._settings.manual_op_channels)

    async def check(self, user: OpContext) -> OpResult:
        channels = self._channels()
        if not channels:
            return OpResult.skip(self.name, "MANUAL_OP_CHANNELS пуст")
        remaining = await check_channels(user.bot, user.user_id, channels)
        if remaining:
            return OpResult.blocked(
                self.name,
                remaining,
                "Подпишитесь на проектные каналы.",
            )
        return OpResult.ok(self.name)

    async def verify(self, user: OpContext) -> OpResult:
        return await self.check(user)


async def check_channels(
    bot: Bot | None,
    user_id: int,
    channels: list[str],
) -> list[Sponsor]:
    if bot is None:
        return [
            Sponsor(title=channel, url=_url_for(channel), kind="channel")
            for channel in channels
        ]
    remaining: list[Sponsor] = []
    for channel in channels:
        try:
            member = await bot.get_chat_member(chat_id=_chat_id(channel), user_id=user_id)
            if member.status not in _SUBSCRIBED:
                remaining.append(
                    Sponsor(title=channel, url=_url_for(channel), kind="channel")
                )
        except TelegramAPIError:
            # Fail-open for a single unreachable chat: do not block the whole gate.
            continue
    return remaining


def _chat_id(raw: str) -> str | int:
    if raw.startswith("@") or not raw.lstrip("-").isdigit():
        return raw
    return int(raw)


def _url_for(channel: str) -> str:
    if channel.startswith("http"):
        return channel
    if channel.startswith("@"):
        return f"https://t.me/{channel[1:]}"
    return f"https://t.me/{channel.lstrip('-')}"
