from app.db.models import User, Withdrawal
from app.services.levels import LevelInfo


def home(
    user: User,
    balance: int,
    level: LevelInfo,
    boost_bp: int,
    bot_username: str,
) -> str:
    next_line = (
        f"До {level.next_level} ур.: {level.next_xp - user.xp} XP"
        if level.next_xp is not None
        else "Максимальный уровень"
    )
    boost = f"{boost_bp / 100:.2f}".rstrip("0").rstrip(".")
    return (
        f"<b>KodoStars</b> · внутренние Stars\n\n"
        f"Привет, {user.first_name or 'друг'}!\n"
        f"Баланс: <b>{balance}</b> ⭐\n"
        f"Уровень {level.level} · множитель ×{level.multiplier_bp / 100:.2f}\n"
        f"Буст: ×{boost} · серия {user.streak} дн.\n"
        f"{next_line}\n\n"
        f"Реф-ссылка:\n"
        f"<code>https://t.me/{bot_username}?start=ref_{user.id}</code>"
    )


def profile(user: User, balance: int, level: LevelInfo, refs: dict[int, int]) -> str:
    status = "заблокирован" if user.is_banned else "активен"
    return (
        f"<b>Профиль</b>\n\n"
        f"ID: <code>{user.id}</code>\n"
        f"Статус: {status}\n"
        f"Баланс: <b>{balance}</b> ⭐\n"
        f"Уровень {level.level} · {user.xp} XP\n"
        f"Активность: {user.activity_score}\n"
        f"Рефералы L1 / L2: {refs.get(1, 0)} / {refs.get(2, 0)}\n"
        f"Активация рефки: {'да' if user.referral_activated else 'ещё нет'}"
    )


def referrals(user: User, bot_username: str, stats: dict[int, int], settings_min: int) -> str:
    return (
        f"<b>Рефералы</b>\n\n"
        f"Многоуровневая сетка (по умолчанию 2 уровня).\n"
        f"Бонус начисляется, когда реферал набирает {settings_min} очков активности "
        f"(ежедневка, задания, буст).\n\n"
        f"L1: {stats.get(1, 0)} чел.\n"
        f"L2: {stats.get(2, 0)} чел.\n\n"
        f"Ваша ссылка:\n"
        f"<code>https://t.me/{bot_username}?start=ref_{user.id}</code>"
    )


def daily_ok(amount: int, streak: int) -> str:
    return f"Ежедневная награда: <b>+{amount} ⭐</b>\nСерия: {streak} дн. подряд."


def daily_wait() -> str:
    return "Сегодня уже забрано. Возвращайтесь завтра — серия вырастет."


def tasks_header() -> str:
    return (
        "<b>Задания</b>\n\n"
        "Закрывайте цели, чтобы получать Stars и XP. "
        "Часть заданий засчитывается автоматически."
    )


def boosts_header() -> str:
    return (
        "<b>Бусты за Telegram Stars</b>\n\n"
        "Оплата только в XTR. После успешного платежа пакет или множитель "
        "начисляется сразу. Это покупка цифрового буста внутри бота."
    )


def withdraw_home(balance: int, minimum: int, cooldown_h: int) -> str:
    return (
        f"<b>Вывод Stars</b>\n\n"
        f"Баланс: <b>{balance}</b> ⭐\n"
        f"Минимум заявки: {minimum} ⭐\n"
        f"Кулдаун: {cooldown_h} ч.\n\n"
        "Выплаты только Telegram Stars. Бот <b>не умеет</b> сам перевести XTR "
        "на ваш аккаунт (в Bot API нет перевода произвольной суммы). "
        "Админ согласует заявку и подтверждает ручную отправку — "
        "списание с леджера происходит только после «Подтвердить отправку»."
    )


def withdraw_created(wd: Withdrawal) -> str:
    return (
        f"Заявка #{wd.id} на <b>{wd.amount} ⭐</b> создана.\n"
        "Статус: ожидает администратора."
    )


def op_blocked(provider: str, extra: str = "") -> str:
    tail = f"\n\n{extra}" if extra else ""
    return (
        f"<b>Обязательная подписка</b>\n"
        f"Провайдер: <code>{provider}</code>\n\n"
        "Подпишитесь на спонсоров, затем нажмите «Я подписался»."
        f"{tail}"
    )


def banned(reason: str) -> str:
    return f"Доступ закрыт.\nПричина: {reason}"


def admin_home() -> str:
    return (
        "<b>Админ-панель KodoStars</b>\n\n"
        "Статистика, очередь выводов, тумблеры OP, рассылка, "
        "импорт пользователей и антифрод."
    )


def admin_import_prompt() -> str:
    return (
        "Пришлите CSV-файл следующим сообщением.\n"
        "Формат: <code>id,username</code> (UTF-8, username без @)."
    )


def admin_import_need_csv() -> str:
    return "Нужен документ с расширением .csv (заголовок id,username)."


def admin_import_result(
    created: int,
    updated: int,
    unchanged: int,
    errors: int,
    error_lines: list[str],
) -> str:
    lines = [
        "<b>Импорт пользователей</b>",
        "",
        f"Создано: {created}",
        f"Обновлено: {updated}",
        f"Без изменений: {unchanged}",
        f"Ошибок: {errors}",
    ]
    if error_lines:
        lines.append("")
        lines.append("Первые ошибки:")
        lines.extend(error_lines[:10])
    return "\n".join(lines)


def admin_stats(data: dict[str, int]) -> str:
    return (
        "<b>Статистика</b>\n\n"
        f"Пользователи: {data['users']}\n"
        f"Баны: {data['banned']}\n"
        f"Начислено Stars: {data['stars_credited']}\n"
        f"Выводы в очереди: {data['withdraw_pending']}\n"
        f"Согласовано вручную: {data['withdraw_approved']}\n"
        f"Отправлено Stars: {data['withdraw_sent_stars']}"
    )


def admin_wd(wd: Withdrawal, username: str | None) -> str:
    uname = f"@{username}" if username else "—"
    return (
        f"<b>Заявка #{wd.id}</b>\n"
        f"Пользователь: <code>{wd.user_id}</code> {uname}\n"
        f"Сумма: {wd.amount} ⭐\n"
        f"Статус: <code>{wd.status}</code>\n"
        f"{wd.admin_note or ''}"
    )
