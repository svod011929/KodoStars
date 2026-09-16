"""Own channels OP (``manual``): membership via ``getChatMember``.

A channel entry in ``MANUAL_OP_CHANNELS`` (or a subscribe-task target) is either
a bare reference or a pipe-separated record::

    @public_channel
    @public_channel|Красивое название
    -1001234567890|https://t.me/+AbCdEfGh|VIP канал
    -1001234567890|https://t.me/+PaidLink|Платный канал

The first field is what the bot *checks* (username or numeric chat id; the bot
must be an administrator there). The link is what the user *taps* — for private
and paid channels it has to be an invite / paid-subscription link, because
``t.me/c/<id>`` only works for existing members. The title is the button label.
"""

from __future__ import annotations

from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from app.config import Settings
from app.op.base import OpContext, OpResult, Sponsor, title_from_link

_SUBSCRIBED = {"creator", "administrator", "member", "restricted"}
_LINK_PREFIXES = ("https://", "http://", "tg://")


@dataclass(frozen=True, slots=True)
class ChannelEntry:
    chat: str | int
    url: str
    title: str
    raw: str

    @property
    def is_private(self) -> bool:
        return isinstance(self.chat, int)

    @property
    def has_join_link(self) -> bool:
        """False when the button would point at ``t.me/c/…`` (members only)."""
        return not self.url.startswith("https://t.me/c/")


class ManualAdapter:
    name = "manual"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _channels(self, ctx: OpContext) -> list[str]:
        settings = ctx.settings or self._settings
        return settings.parse_channel_list(settings.manual_op_channels)

    async def check(self, user: OpContext) -> OpResult:
        channels = self._channels(user)
        if not channels:
            return OpResult.skip(self.name, "MANUAL_OP_CHANNELS пуст")
        remaining = await check_channels(user.bot, user.user_id, channels)
        if remaining:
            return OpResult.blocked(
                self.name,
                remaining,
                "Подпишитесь на каналы проекта, чтобы продолжить.",
            )
        return OpResult.ok(self.name)

    async def verify(self, user: OpContext) -> OpResult:
        return await self.check(user)


def parse_channel_entry(raw: str) -> ChannelEntry:
    parts = [part.strip() for part in raw.split("|")]
    target = parts[0]
    url = ""
    title = ""
    for extra in parts[1:]:
        if not extra:
            continue
        if extra.startswith(_LINK_PREFIXES) and not url:
            url = extra
        elif not title:
            title = extra
    if not url:
        url = url_for(target)
    if not title:
        title = target if target.startswith("@") else title_from_link(url, "Канал")
    return ChannelEntry(chat=chat_ref(target), url=url, title=title, raw=raw)


def format_channel_entry(chat: str | int, url: str | None = None, title: str | None = None) -> str:
    parts = [str(chat)]
    if url:
        parts.append(url.strip())
    if title:
        parts.append(title.replace("|", "/").replace(",", " ").strip()[:48])
    return "|".join(parts)


def validate_channel_entry(raw: str) -> str | None:
    """Return a human-readable problem or None when the entry is usable."""
    if "," in raw:
        return "запятая недопустима внутри записи (это разделитель списка)"
    parts = [part.strip() for part in raw.split("|")]
    target = parts[0]
    if not target:
        return "пустая запись"
    if not (target.startswith("@") and len(target) > 1) and not (
        target.startswith("-100") and target[4:].isdigit()
    ):
        return f"«{target}» — нужен @username или id канала вида -100…"
    links = [part for part in parts[1:] if part.startswith(_LINK_PREFIXES)]
    if len(links) > 1:
        return "укажите одну ссылку"
    if links and not links[0].startswith(("https://t.me/", "http://t.me/", "tg://")):
        return "ссылка должна вести в Telegram (https://t.me/…)"
    entry = parse_channel_entry(raw)
    if entry.is_private and not entry.has_join_link:
        return (
            f"для приватного канала {target} нужна пригласительная ссылка: "
            f"<code>{target}|https://t.me/+…</code>"
        )
    return None


def chat_ref(raw: str) -> str | int:
    target = raw.split("|", 1)[0].strip()
    if target.startswith("@") or not target.lstrip("-").isdigit():
        return target
    return int(target)


def url_for(channel: str) -> str:
    target = channel.split("|", 1)[0].strip()
    if target.startswith(_LINK_PREFIXES):
        return target
    if target.startswith("@"):
        return f"https://t.me/{target[1:]}"
    return f"https://t.me/c/{target.removeprefix('-100')}"


async def is_member(bot: Bot | None, user_id: int, channel: str) -> bool | None:
    """True/False for a definite answer, None when the chat cannot be checked."""
    if bot is None:
        return None
    try:
        member = await bot.get_chat_member(chat_id=chat_ref(channel), user_id=user_id)
    except TelegramAPIError:
        return None
    return member.status in _SUBSCRIBED


def _sponsor(entry: ChannelEntry) -> Sponsor:
    return Sponsor(title=entry.title, url=entry.url, kind="channel")


async def check_channels(
    bot: Bot | None,
    user_id: int,
    channels: list[str],
) -> list[Sponsor]:
    entries = [parse_channel_entry(channel) for channel in channels]
    if bot is None:
        return [_sponsor(entry) for entry in entries]
    remaining: list[Sponsor] = []
    for entry in entries:
        verdict = await is_member(bot, user_id, entry.raw)
        if verdict is False:
            remaining.append(_sponsor(entry))
        # None → fail-open for a single unreachable chat: do not block the whole gate.
    return remaining
