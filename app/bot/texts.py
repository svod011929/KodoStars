"""User-facing texts (Russian, HTML parse mode)."""

from __future__ import annotations

from collections.abc import Sequence

from app.bot.utils import button, fmt_dt, fmt_duration, fmt_signed, h, markup
from app.config import Settings
from app.db.models import (
    LEDGER_KIND_LABELS,
    WITHDRAWAL_STATUS_LABELS,
    LedgerEntry,
    PromoCode,
    Task,
    TaskKind,
    User,
    UserBoost,
    Withdrawal,
)
from app.services.channels import parse_channel_entry
from app.services.daily import DailyPreview
from app.services.leaderboard import LeaderRow
from app.services.levels import LevelInfo, format_multiplier, progress_bar
from app.services.tasks import task_target

STAR = "⭐"


def home(
    user: User,
    balance: int,
    held: int,
    level: LevelInfo,
    boost_bp: int,
    boost_until: str | None,
    link: str,
    device_notice: str = "",
) -> str:
    if level.next_xp is not None:
        level_line = (
            f"🏅 Уровень {level.level} {progress_bar(level.progress(user.xp))} {user.xp}/{level.next_xp} XP"
        )
    else:
        level_line = f"🏅 Уровень {level.level} — максимальный"
    hold = f" · в холде {held} {STAR}" if held else ""
    boost = format_multiplier(boost_bp)
    boost_line = f"✨ Множитель {format_multiplier(level.multiplier_bp)}"
    if boost_bp > 100:
        boost_line += f" · буст {boost}" + (f" до {boost_until}" if boost_until else "")
    notice = f"\n\n{device_notice}" if device_notice else ""
    return (
        f"{STAR} <b>KodoStars</b>\n\n"
        f"Привет, {h(user.first_name or 'друг')}!\n\n"
        f"💰 Баланс: <b>{balance} {STAR}</b>{hold}\n"
        f"{level_line}\n"
        f"{boost_line}\n"
        f"🔥 Серия ежедневок: {user.streak} дн.\n\n"
        f"🔗 Твоя реферальная ссылка:\n<code>{h(link)}</code>\n\n"
        "Зови друзей, забирай ежедневку, выполняй задания — и выводи Stars."
        f"{notice}"
    )


def device_notice(for_withdraw: bool) -> str:
    bits = ["не засчитываются рефералы"]
    if for_withdraw:
        bits.append("недоступен вывод")
    bits.append("не выдаются задания ОП")
    return (
        "🛡 <b>Подтвердите устройство</b> — одна кнопка, две секунды. "
        f"Без этого {', '.join(bits)}."
    )


def device_twink_notice() -> str:
    return (
        "⚠️ На этом устройстве уже есть другой аккаунт: реферальные бонусы за этот аккаунт "
        "не начисляются, задания ОП не выдаются. Если это ошибка — напишите в поддержку."
    )


def op_need_device() -> str:
    return (
        "🛡 <b>Сначала подтвердите устройство</b>\n\n"
        "Это нужно, чтобы отсеять мультиаккаунты до выдачи заданий спонсоров. "
        "Нажмите кнопку ниже — займёт пару секунд."
    )


def op_twink_blocked(support: str) -> str:
    contact = f"\n\nПоддержка: {h(support)}" if support else ""
    return (
        "⚠️ <b>Доступ ограничен</b>\n\n"
        "С этого устройства уже зарегистрирован другой аккаунт, поэтому задания "
        "обязательной подписки не выдаются."
        f"{contact}"
    )


def notify_device_verified(twink: bool, first_time: bool) -> str:
    if twink:
        return (
            "🛡 Устройство проверено.\n\n"
            "⚠️ На нём уже зарегистрирован другой аккаунт, поэтому реферальные бонусы и задания "
            "ОП за этот аккаунт недоступны. Если это ошибка — напишите в поддержку."
        )
    if first_time:
        return "🛡 Устройство подтверждено ✅ Можно продолжать — дальше откроются задания спонсоров."
    return "🛡 Устройство подтверждено ✅"


def notify_piarflow_unsubscribed(penalty: int) -> str:
    if penalty > 0:
        return (
            f"⚠️ Вы отписались от спонсора. С баланса списано <b>{penalty} {STAR}</b>, "
            "доступ к боту снова требует подписки."
        )
    return "⚠️ Вы отписались от спонсора. Доступ к боту снова требует подписки."


def home_button():
    return markup([button("🏠 В меню", "menu:home")])


def profile(
    user: User,
    balance: int,
    held: int,
    level: LevelInfo,
    refs: dict[int, int],
    ref_earned: int,
    boosts: Sequence[UserBoost],
    boost_titles: dict[int, str],
) -> str:
    status = "🚫 заблокирован" if user.is_banned else "✅ активен"
    if level.next_xp is not None:
        lvl = f"{level.level} ({user.xp}/{level.next_xp} XP)"
    else:
        lvl = f"{level.level} (макс.)"
    lines = [
        "👤 <b>Профиль</b>",
        "",
        f"ID: <code>{user.id}</code>",
        f"Статус: {status}",
        f"💰 Баланс: <b>{balance} {STAR}</b>",
    ]
    if held:
        lines.append(f"⏳ В холде (заявки на вывод): {held} {STAR}")
    lines += [
        f"🏅 Уровень: {lvl} · множитель {format_multiplier(level.multiplier_bp)}",
        f"🔥 Серия: {user.streak} дн.",
        f"⚡ Активность: {user.activity_score}",
        f"👥 Рефералы: L1 — {refs.get(1, 0)}, L2 — {refs.get(2, 0)}",
        f"💎 Заработано с рефералов: {ref_earned} {STAR}",
        f"🎯 Активация рефки: {'да' if user.referral_activated else 'ещё нет'}",
        f"📅 С нами с: {fmt_dt(user.created_at, with_time=False)}",
    ]
    if boosts:
        lines.append("")
        lines.append("🚀 <b>Активные бусты</b>")
        for boost in boosts:
            title = boost_titles.get(boost.product_id, "Буст")
            lines.append(
                f"• {h(title)} {format_multiplier(boost.multiplier_bp)} до {fmt_dt(boost.expires_at)}"
            )
    return "\n".join(lines)


def history(entries: Sequence[LedgerEntry], page: int, total: int, page_size: int) -> str:
    if not entries:
        return "📜 <b>История операций</b>\n\nПока пусто. Заберите ежедневку — это первый плюс!"
    lines = ["📜 <b>История операций</b>", ""]
    for entry in entries:
        label = LEDGER_KIND_LABELS.get(entry.kind, entry.kind)
        lines.append(
            f"{'➕' if entry.amount > 0 else '➖'} <b>{fmt_signed(entry.amount)} {STAR}</b> — "
            f"{h(label)}\n   <i>{fmt_dt(entry.created_at)}</i> · баланс {entry.balance_after}"
        )
    pages = max((total + page_size - 1) // page_size, 1)
    lines.append("")
    lines.append(f"Страница {page + 1} из {pages} · всего операций: {total}")
    return "\n".join(lines)


def referrals(
    user: User,
    link: str,
    stats: dict[int, int],
    activated_l1: int,
    earned: int,
    rank: int | None,
    settings: Settings,
    recent: Sequence[User],
) -> str:
    lines = [
        "👥 <b>Рефералы</b>",
        "",
        f"L1 (твои друзья): <b>{settings.referral_l1_bonus} {STAR}</b> за активацию + "
        f"<b>{settings.referral_l1_percent}%</b> с их заработка.",
    ]
    if settings.referral_levels >= 2:
        lines.append(
            f"L2 (друзья друзей): <b>{settings.referral_l2_bonus} {STAR}</b> + "
            f"<b>{settings.referral_l2_percent}%</b>."
        )
    lines += [
        f"Активация — когда друг набирает {settings.min_referral_activity} очк. активности "
        "(ежедневка, задания, промокод, буст).",
        "",
        f"👤 L1: <b>{stats.get(1, 0)}</b> (активных {activated_l1}) · L2: <b>{stats.get(2, 0)}</b>",
        f"💎 Заработано: <b>{earned} {STAR}</b>",
    ]
    if rank:
        lines.append(f"🏆 Место в топе рефереров: #{rank}")
    lines += ["", "🔗 Ссылка:", f"<code>{h(link)}</code>"]
    if recent:
        lines += ["", "Недавние рефералы:"]
        for ref in recent:
            mark = "✅" if ref.referral_activated else "⏳"
            lines.append(f"{mark} {h(ref.first_name or ref.display_name)}")
    return "\n".join(lines)


def share_text(link: str, signup_bonus: int) -> str:
    bonus = f" Бонус {signup_bonus} ⭐ за старт!" if signup_bonus else ""
    return f"Зарабатывай Telegram Stars за друзей и ежедневки в KodoStars.{bonus} {link}"


def daily_screen(preview: DailyPreview, settings: Settings) -> str:
    if preview.claimed_today:
        return (
            "🎁 <b>Ежедневная награда</b>\n\n"
            "Сегодня уже забрано ✅\n"
            f"Следующая награда через <b>{fmt_duration(preview.seconds_until_reset)}</b>: "
            f"≈{preview.estimated_reward} {STAR} (серия {preview.streak_if_claimed} дн.).\n\n"
            "Не пропускай день — серия сбросится."
        )
    return (
        "🎁 <b>Ежедневная награда</b>\n\n"
        f"Сегодня: <b>≈{preview.estimated_reward} {STAR}</b> "
        f"(база {preview.base_reward}, серия станет {preview.streak_if_claimed} дн.)\n"
        f"Каждый день серии +{settings.daily_streak_bonus} {STAR}, максимум "
        f"+{settings.daily_streak_cap * settings.daily_streak_bonus} {STAR}.\n\n"
        "Нажми «Забрать»!"
    )


def daily_ok(amount: int, streak: int) -> str:
    return (
        f"🎁 Ежедневная награда: <b>+{amount} {STAR}</b>\n🔥 Серия: {streak} дн. подряд. Возвращайся завтра!"
    )


def daily_wait() -> str:
    return "Сегодня уже забрано. Возвращайтесь завтра — серия вырастет."


def tasks_header(done: int, total: int) -> str:
    return (
        "📋 <b>Задания</b>\n\n"
        f"Выполнено: {done} из {total}.\n"
        "Награда умножается на твой уровень и активный буст. "
        "Часть заданий засчитывается автоматически."
    )


def task_card(task: Task, done: bool) -> str:
    target = task_target(task)
    lines = [f"📌 <b>{h(task.title)}</b>", ""]
    if task.description:
        lines += [h(task.description), ""]
    lines.append(f"Награда: <b>+{task.reward} {STAR}</b> (до множителей)")
    if task.kind == TaskKind.SUBSCRIBE.value and target:
        lines.append(f"Условие: подписка на {h(parse_channel_entry(target).title)}")
    elif task.kind == TaskKind.INVITE.value:
        lines.append(f"Условие: {h(target)} с активацией")
    elif task.kind == TaskKind.STREAK.value:
        lines.append(f"Условие: серия ежедневок {h(target)}")
    elif task.kind == TaskKind.CUSTOM.value and target:
        lines.append("Условие: перейти по ссылке и нажать «Получить»")
    if done:
        lines += ["", "✅ Выполнено"]
    return "\n".join(lines)


def boosts_header(active: Sequence[UserBoost], titles: dict[int, str]) -> str:
    lines = [
        "🚀 <b>Бусты за Telegram Stars</b>",
        "",
        "Оплата в XTR прямо в Telegram. После оплаты пакет или множитель "
        "начисляется мгновенно. Это цифровой товар внутри бота.",
    ]
    if active:
        lines += ["", "Активные:"]
        for boost in active:
            lines.append(
                f"• {h(titles.get(boost.product_id, 'Буст'))} "
                f"{format_multiplier(boost.multiplier_bp)} до {fmt_dt(boost.expires_at)}"
            )
    return "\n".join(lines)


def boost_card(title: str, description: str, price: int, detail: str) -> str:
    return f"🚀 <b>{h(title)}</b>\n\n{h(description)}\n\n{detail}\nЦена: <b>{price} XTR</b>"


def top(
    rows_refs: Sequence[LeaderRow], rows_earn: Sequence[LeaderRow], mode: str, my_rank: int | None
) -> str:
    medals = ["🥇", "🥈", "🥉"]
    if mode == "earn":
        title = "🏆 <b>Топ по заработку за 7 дней</b>"
        rows = rows_earn
        unit = STAR
    else:
        title = "🏆 <b>Топ по рефералам</b>"
        rows = rows_refs
        unit = "реф."
    lines = [title, ""]
    if not rows:
        lines.append("Пока пусто — стань первым!")
    for index, row in enumerate(rows):
        medal = medals[index] if index < 3 else f"{index + 1}."
        lines.append(f"{medal} {h(row.name)} — <b>{row.value}</b> {unit}")
    if mode != "earn" and my_rank:
        lines += ["", f"Твоё место: #{my_rank}"]
    return "\n".join(lines)


def withdraw_home(
    balance: int,
    held: int,
    settings: Settings,
    open_request: Withdrawal | None,
    *,
    offers_count: int = 0,
    catalog_error: bool = False,
    can_pick: bool = True,
) -> str:
    lines = [
        "💸 <b>Вывод Stars</b>",
        "",
        f"Доступно: <b>{balance} {STAR}</b>",
    ]
    if held:
        lines.append(f"В холде: {held} {STAR}")
    limits = f"Минимум: {settings.withdraw_min} {STAR}"
    if settings.withdraw_max:
        limits += f" · максимум: {settings.withdraw_max} {STAR}"
    lines += [limits, f"Кулдаун между заявками: {settings.withdraw_cooldown_hours} ч."]
    if settings.withdraw_min_referrals:
        lines.append(f"Нужно активных рефералов: {settings.withdraw_min_referrals}")
    if not settings.withdraw_enabled:
        lines += ["", "⛔ Вывод временно приостановлен."]
    if open_request is not None:
        lines += [
            "",
            f"Открытая заявка #{open_request.id}: <b>{h(open_request.gift_label)}</b> — "
            f"{WITHDRAWAL_STATUS_LABELS.get(open_request.status, open_request.status)}.",
        ]
    elif can_pick and catalog_error:
        lines += ["", "⚠️ Не удалось загрузить каталог подарков Telegram. Попробуйте обновить."]
    elif can_pick and balance < settings.withdraw_min:
        lines += ["", f"Накопите ещё {settings.withdraw_min - balance} {STAR}, чтобы выбрать подарок."]
    elif can_pick and offers_count == 0:
        lines += ["", "Сейчас нет доступных подарков на ваш баланс. Накопите больше Stars."]
    elif can_pick:
        lines += [
            "",
            "Выберите готовый подарок Telegram — его стоимость спишется с баланса. "
            "Администратор проверит заявку и отправит подарок (обычно в течение суток). "
            "Если заявку отклонят, Stars вернутся на баланс.",
        ]
    return "\n".join(lines)


def withdraw_created(wd: Withdrawal) -> str:
    return (
        f"✅ Заявка #{wd.id} на <b>{h(wd.gift_label)}</b> создана.\n"
        "Сумма зарезервирована. Мы уведомим вас, когда администратор её обработает."
    )


def withdraw_list(items: Sequence[Withdrawal]) -> str:
    if not items:
        return "📄 <b>Мои заявки</b>\n\nЗаявок ещё не было."
    lines = ["📄 <b>Мои заявки</b>", ""]
    for wd in items:
        status = WITHDRAWAL_STATUS_LABELS.get(wd.status, wd.status)
        lines.append(f"#{wd.id} · {h(wd.gift_label)} · {status} · {fmt_dt(wd.created_at)}")
        if wd.status == "rejected" and wd.admin_note:
            lines.append(f"   <i>{h(wd.admin_note)}</i>")
    return "\n".join(lines)


def withdraw_status_update(wd: Withdrawal, status: str, note: str) -> str:
    if status == "approved_manual":
        return (
            f"🟢 Заявка #{wd.id} на {h(wd.gift_label)} согласована.\n"
            "Администратор скоро отправит подарок Stars."
        )
    if status == "sent":
        return f"💸 Заявка #{wd.id}: подарок <b>{h(wd.gift_label)}</b> отправлен. Спасибо, что с нами!"
    if status == "rejected":
        reason = f"\nПричина: {h(note)}" if note else ""
        return (
            f"🔴 Заявка #{wd.id} на {h(wd.gift_label)} отклонена. "
            f"Stars возвращены на баланс.{reason}"
        )
    return f"Заявка #{wd.id}: статус — {WITHDRAWAL_STATUS_LABELS.get(status, status)}."


def promo_prompt() -> str:
    return "🎟 Введите промокод одним сообщением.\nИли нажмите «Отмена»."


def promo_ok(promo: PromoCode, amount: int) -> str:
    return f"🎟 Промокод <code>{h(promo.code)}</code> активирован: <b>+{amount} {STAR}</b>!"


def op_blocked(provider: str, extra: str = "") -> str:
    tail = f"\n\n{h(extra)}" if extra else ""
    return (
        "🔒 <b>Обязательная подписка</b>\n\n"
        "Чтобы пользоваться ботом, подпишитесь на спонсоров ниже, "
        "затем нажмите «Я подписался»."
        f"{tail}"
    )


def banned(reason: str, support: str = "") -> str:
    contact = f"\nПоддержка: {h(support)}" if support else ""
    return f"🚫 Доступ закрыт.\nПричина: {h(reason)}{contact}"


def banned_short() -> str:
    return "Доступ закрыт"


def help_text(settings: Settings, is_admin: bool) -> str:
    support = f"\n\n📨 Поддержка: {h(settings.support_contact)}" if settings.support_contact else ""
    admin = "\n\n/admin — панель администратора" if is_admin else ""
    return (
        "❓ <b>Как это работает</b>\n\n"
        f"• <b>Ежедневка</b> — каждый день забирай {settings.daily_base_reward}+ {STAR}, "
        "серия увеличивает награду.\n"
        "• <b>Задания</b> — подписки, приглашения, серии. Награда × уровень × буст.\n"
        f"• <b>Рефералы</b> — {settings.referral_l1_bonus} {STAR} за активного друга и "
        f"{settings.referral_l1_percent}% с его заработка (плюс 2-й уровень).\n"
        "• <b>Уровни</b> — XP за любые действия, множитель до ×2.\n"
        "• <b>Бусты</b> — множители и паки за Telegram Stars (XTR).\n"
        f"• <b>Вывод</b> — от {settings.withdraw_min} {STAR}, выбор готового подарка Telegram.\n\n"
        "Команды: /menu — меню, /profile — профиль, /help — эта справка, "
        "/paysupport — вопросы по оплате."
        f"{support}{admin}"
    )


def paysupport(settings: Settings) -> str:
    contact = h(settings.support_contact) if settings.support_contact else "администратору бота"
    return (
        "💳 <b>Поддержка по платежам</b>\n\n"
        "Бусты — цифровые товары, они начисляются сразу после оплаты в Telegram Stars.\n"
        "Если оплата прошла, а буст не появился, или вы хотите вернуть покупку — "
        f"напишите {contact}, укажите ID платежа из чека.\n"
        "Возврат возможен в течение 21 дня, если буст не был использован."
    )


def terms(settings: Settings) -> str:
    contact = f" Контакт: {h(settings.support_contact)}." if settings.support_contact else ""
    return (
        "📄 <b>Условия</b>\n\n"
        "1. Внутренние Stars начисляются за активность и не являются платёжным средством "
        "вне бота.\n"
        "2. Одна учётная запись на человека. Накрутка рефералов ведёт к блокировке и "
        "аннулированию баланса.\n"
        "3. Заявки на вывод проверяются вручную; администратор может запросить "
        "подтверждение активности.\n"
        "4. Покупки бустов — цифровые товары; возврат согласно /paysupport.\n"
        f"5. Администрация вправе менять условия экономики.{contact}"
    )


def payment_done(title: str, charge_id: str) -> str:
    return (
        f"✅ Оплата прошла. <b>{h(title)}</b> активирован.\n"
        f"Чек Telegram: <code>{h(charge_id)}</code>\n"
        "Вопросы по оплате — /paysupport"
    )


def unknown_message() -> str:
    return "Я понимаю только кнопки и команды. Откройте меню: /menu"


def maintenance(settings: Settings) -> str:
    return settings.maintenance_text


def notify_referral_joined(name: str) -> str:
    return f"👥 По твоей ссылке пришёл новый друг: <b>{h(name)}</b>. Бонус будет после активации."


def notify_referral_activated(name: str, level: int, amount: int) -> str:
    who = "твой реферал" if level == 1 else "реферал 2-го уровня"
    return f"💎 {who.capitalize()} <b>{h(name)}</b> активировался: <b>+{amount} {STAR}</b>!"


def notify_task_completed(title: str, amount: int) -> str:
    return f"📋 Задание «{h(title)}» выполнено автоматически: <b>+{amount} {STAR}</b>"


def notify_balance_adjusted(amount: int, reason: str) -> str:
    sign = "начислил" if amount > 0 else "списал"
    tail = f"\nКомментарий: {h(reason)}" if reason else ""
    return f"⚙️ Администратор {sign} <b>{abs(amount)} {STAR}</b>.{tail}"


def notify_refund(xtr: int, revoked: int, title: str) -> str:
    revoked_line = f"\nС баланса списано {revoked} {STAR}." if revoked else ""
    return f"↩️ Покупка «{h(title)}» возвращена: {xtr} XTR вернутся на ваш счёт Telegram.{revoked_line}"
