"""Admin panel texts (Russian, HTML)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.bot import emoji as pe
from app.bot.utils import fmt_ago, fmt_dt, fmt_signed, h, mention
from app.config import (
    RUNTIME_OVERRIDABLE,
    RUNTIME_SETTING_LABELS,
    SETTINGS_GROUP_LABELS,
    SETTINGS_GROUPS,
    Settings,
)
from app.db.models import (
    AMBASSADOR_KIND_LABELS,
    AMBASSADOR_STATUS_LABELS,
    BROADCAST_AUDIENCE_LABELS,
    LEDGER_KIND_LABELS,
    TASK_KIND_LABELS,
    WITHDRAWAL_STATUS_LABELS,
    Admin,
    AdminAction,
    AmbassadorSlot,
    AmbassadorStatus,
    BoostKind,
    BoostProduct,
    Broadcast,
    FraudEvent,
    LedgerEntry,
    Payment,
    PromoCode,
    Task,
    User,
    Withdrawal,
)
from app.op.gate import CASCADE, PROVIDER_DOCS, PROVIDER_TITLES
from app.services.app_settings import format_value
from app.services.promo import activation_link
from app.services.audit import label as action_label
from app.services.boosts import describe as describe_boost
from app.services.stats import Dashboard
from app.services.tasks import task_target


class _CurrencyGlyph:
    __slots__ = ()

    def __str__(self) -> str:
        return pe.currency()

    def __format__(self, spec: str) -> str:
        return format(str(self), spec)


STAR = _CurrencyGlyph()


def home(version: str, pending: int, running_broadcast: bool, maintenance: bool) -> str:
    flags = []
    if maintenance:
        flags.append("обслуживание")
    if running_broadcast:
        flags.append("рассылка")
    status = f" · {' · '.join(flags)}" if flags else ""
    queue = f" · очередь выводов: <b>{pending}</b>" if pending else ""
    return (
        f"🛠 <b>Админка</b> <i>v{h(version)}</i>{status}{queue}\n\n"
        "<b>Операции</b> — статистика, пользователи, выводы, амбассадоры, рассылка\n"
        "<b>Каталог</b> — задания, бусты, промокоды\n"
        "<b>PiarFlow</b> — ОП и трафик\n"
        "<b>Система</b> — платежи, админы, журнал, антифрод, данные"
    )


def catalog_hub() -> str:
    return (
        "📦 <b>Каталог</b>\n\n"
        "Задания, бусты, промокоды, приветки и кампании закупки."
    )


def system_hub() -> str:
    return (
        "⚙️ <b>Система</b>\n\n"
        "Платежи XTR, админы, журнал действий, антифрод и экспорт данных."
    )


def stats(
    d: Dashboard,
    star_balance: int | None,
    days: Sequence[tuple[str, int]],
    pf=None,
) -> str:
    kinds = "\n".join(
        f"   • {h(LEDGER_KIND_LABELS.get(kind, kind))}: {total}"
        for kind, total in sorted(d.credited_by_kind.items(), key=lambda kv: -kv[1])
    )
    lb = d.last_broadcast
    last_bc = f"#{lb.id} · {lb.status} · {lb.sent}/{lb.total} · {fmt_ago(lb.created_at)}" if lb else "—"
    star_line = f"\n💫 Баланс Stars бота: <b>{star_balance}</b> XTR" if star_balance is not None else ""
    spark = " ".join(f"{day[5:]}:{count}" for day, count in days) or "—"
    pf_line = ""
    if pf is not None:
        pf_line = (
            f"\n\n📣 PiarFlow: выдано {pf.issued_total} (сегодня {pf.issued_today}) · "
            f"засчитано {pf.credited_total} (сегодня {pf.credited_today}) · "
            f"конверсия {pf.conversion_pct:.0f}%"
        )
    return (
        "📊 <b>Статистика</b>\n\n"
        f"👥 Пользователи: <b>{d.users_total}</b> "
        f"(+{d.users_today} сегодня, +{d.users_7d} за 7 дн, +{d.users_30d} за 30 дн)\n"
        f"📈 Регистрации по дням: {spark}\n"
        f"🟢 DAU / WAU: {d.dau} / {d.wau}\n"
        f"🚫 Баны: {d.banned} · заблокировали бота: {d.blocked_bot}\n\n"
        f"🔗 Пришли по рефке: {d.referred} · активировались: {d.activated} "
        f"({d.activation_rate:.0f}%)\n\n"
        f"💰 Сумма балансов: <b>{d.total_balance} {STAR}</b> · в холде: {d.held} {STAR}\n"
        f"➕ Начислено всего: {d.credited_total} {STAR} (сегодня {d.credited_today})\n"
        f"{kinds}\n\n"
        f"💸 Выводы: ожидают {d.withdraw_pending_count} ({d.withdraw_pending_sum} {STAR}) · "
        f"согласованы {d.withdraw_approved_count} ({d.withdraw_approved_sum} {STAR})\n"
        f"   выплачено {d.withdraw_sent_count} ({d.withdraw_sent_sum} {STAR}) · "
        f"отклонено {d.withdraw_rejected_count}\n\n"
        f"💳 Платежи: {d.payments_count} · выручка <b>{d.revenue_xtr} XTR</b> "
        f"(30 дн: {d.revenue_xtr_30d}) · возвратов {d.refunds_count}{star_line}\n\n"
        f"🎁 Ежедневок сегодня: {d.daily_claims_today} · 📋 заданий выполнено: {d.tasks_completed} · "
        f"🎟 промо: {d.promo_redemptions}\n"
        f"🛡 Устройство подтвердили: {d.device_verified} · 👯 твинков: {d.twinks}\n"
        f"📣 Последняя рассылка: {last_bc}"
        f"{pf_line}"
    )


def piarflow_traffic(t) -> str:
    return (
        "📊 <b>PiarFlow · трафик</b>\n\n"
        f"📤 Выдано спонсоров (уник. user+link): <b>{t.issued_total}</b>\n"
        f"   сегодня {t.issued_today} · 7 дн {t.issued_7d} · показов всего {t.shows_total}\n"
        f"   уникальных пользователей: {t.unique_users_issued}\n\n"
        f"✅ Засчитано (subscribed): <b>{t.credited_total}</b>\n"
        f"   сегодня {t.credited_today} · 7 дн {t.credited_7d}\n"
        f"   уникальных пользователей: {t.unique_users_credited}\n\n"
        f"📈 Конверсия выдача→зачёт: <b>{t.conversion_pct:.1f}%</b>\n"
        f"↩️ Отписок (вебхук): {t.unsubs_total} (сегодня {t.unsubs_today})"
    )


def piarflow_issued_list(rows, names: dict[int, str], page: int, total: int, page_size: int) -> str:
    lines = ["📤 <b>Выданные спонсоры</b>", ""]
    if not rows:
        lines.append("Пока пусто — задания ещё не выдавались.")
    for row in rows:
        name = h(names.get(row.user_id, str(row.user_id)))
        link = h(row.offer_link[:48] + ("…" if len(row.offer_link) > 48 else ""))
        lines.append(
            f"• <code>{row.user_id}</code> {name}\n"
            f"  {link}\n"
            f"  показов {row.show_count} · последний {fmt_ago(row.last_shown_at)}"
        )
    pages = max((total + page_size - 1) // page_size, 1)
    lines += ["", f"Страница {page + 1}/{pages} · всего {total}"]
    return "\n".join(lines)


def piarflow_credited_list(rows, names: dict[int, str], page: int, total: int, page_size: int) -> str:
    lines = ["✅ <b>Засчитанные подписки</b>", ""]
    if not rows:
        lines.append("Пока пусто — PiarFlow ещё не засчитал subscribed.")
    for row in rows:
        name = h(names.get(row.user_id, str(row.user_id)))
        link = h(row.offer_link[:48] + ("…" if len(row.offer_link) > 48 else ""))
        lines.append(
            f"• <code>{row.user_id}</code> {name}\n"
            f"  {link}\n"
            f"  {fmt_ago(row.created_at)}"
        )
    pages = max((total + page_size - 1) // page_size, 1)
    lines += ["", f"Страница {page + 1}/{pages} · всего {total}"]
    return "\n".join(lines)


def reconcile(rows: Sequence[tuple[int, int, int]]) -> str:
    if not rows:
        return "🧮 <b>Сверка балансов</b>\n\nРасхождений между леджером и балансами нет ✅"
    lines = ["🧮 <b>Сверка балансов</b>", "", "Пользователь · balance · сумма леджера"]
    for uid, balance, total in rows:
        lines.append(f"<code>{uid}</code> · {balance} · {total} (Δ {fmt_signed(balance - total)})")
    lines += ["", "Нажмите «Исправить», чтобы выровнять balance по леджеру."]
    return "\n".join(lines)


# --- users --------------------------------------------------------------------------


def users_home(recent: Sequence[User], total: int) -> str:
    lines = [
        "👥 <b>Пользователи</b>",
        "",
        f"Всего: <b>{total}</b>. Отправьте ID или @username сообщением, чтобы открыть карточку.",
        "",
        "Недавние регистрации:",
    ]
    for user in recent:
        lines.append(f"• <code>{user.id}</code> {h(user.display_name)} · {fmt_ago(user.created_at)}")
    return "\n".join(lines)


def user_card(
    user: User,
    *,
    balance: int,
    held: int,
    refs: dict[int, int],
    activated: int,
    ref_earned: int,
    payments_count: int,
    payments_xtr: int,
    withdrawals_sent: int,
    open_wd: Withdrawal | None,
    fraud_count: int,
    referrer: User | None,
    is_admin: bool,
    linked: Sequence[User] = (),
    device_check_active: bool | None = None,
) -> str:
    status = "🚫 БАН" if user.is_banned else "✅ активен"
    if user.blocked_bot_at:
        status += " · ⛔ заблокировал бота"
    if is_admin:
        status += " · 🛠 админ"
    if user.is_trusted:
        status += " · 🤝 доверенный"
    elif user.twink_of is not None:
        status += " · 👯 твинк"
    lines = [
        f"👤 <b>{h(user.display_name)}</b> {mention(user.id, 'открыть')}",
        f"ID: <code>{user.id}</code> · {status}",
        f"Имя: {h(user.first_name or '—')} · язык {h(user.language_code)} · "
        f"{'Premium' if user.is_premium else 'без Premium'}",
        "",
        f"💰 Баланс: <b>{balance} {STAR}</b>" + (f" · холд {held}" if held else ""),
        f"🏅 Уровень {user.level} · {user.xp} XP · серия {user.streak} · активность {user.activity_score}",
        f"👥 Рефералы L1/L2: {refs.get(1, 0)}/{refs.get(2, 0)} · активных {activated} · "
        f"заработано {ref_earned} {STAR}",
        f"🔗 Реферер: {h(referrer.display_name) if referrer else '—'} · "
        f"активация: {'да' if user.referral_activated else 'нет'}",
        f"💳 Платежи: {payments_count} на {payments_xtr} XTR · 💸 выплачено {withdrawals_sent} {STAR}",
        f"🕵️ Фрод-событий: {fraud_count}",
        f"📅 Регистрация {fmt_dt(user.created_at)} · активность {fmt_ago(user.last_action_at)}",
    ]
    if open_wd is not None:
        lines.append(
            f"⏳ Открытая заявка #{open_wd.id}: {h(open_wd.gift_label)} · "
            f"{WITHDRAWAL_STATUS_LABELS.get(open_wd.status, open_wd.status)}"
        )
    if user.is_banned and user.ban_reason:
        lines.append(f"Причина бана: <i>{h(user.ban_reason)}</i>")
    lines.append(device_line(user, linked, device_check_active))
    if user.admin_note:
        lines += ["", f"📝 Заметка: <i>{h(user.admin_note)}</i>"]
    return "\n".join(lines)


def device_line(user: User, linked: Sequence[User], active: bool | None) -> str:
    if user.device_verified_at is None:
        return "🛡 Устройство: не подтверждено" + (" (проверка выключена)" if active is False else "")
    fp = (user.device_fp or "")[:10]
    line = f"🛡 Устройство: подтверждено {fmt_dt(user.device_verified_at)} · fp <code>{h(fp)}</code>"
    if linked:
        others = ", ".join(f"<code>{item.id}</code>" for item in linked[:5])
        more = f" +{len(linked) - 5}" if len(linked) > 5 else ""
        line += f"\n👯 То же устройство: {others}{more}"
        if user.twink_of is not None and not user.is_trusted:
            line += f" · первый аккаунт <code>{user.twink_of}</code>"
    return line


def twinks_report(clusters: Sequence[tuple[str, int, Sequence[User]]], stats: dict[str, int]) -> str:
    lines = [
        "👯 <b>Твинки (одно устройство — несколько аккаунтов)</b>",
        "",
        f"Проверили устройство: {stats.get('verified', 0)} · твинков: {stats.get('twinks', 0)} · "
        f"доверенных: {stats.get('trusted', 0)}",
        "",
    ]
    if not clusters:
        lines.append("Совпадений устройств нет.")
    for fp, count, members in clusters:
        names = ", ".join(f"<code>{m.id}</code>{' 🤝' if m.is_trusted else ''}" for m in members)
        lines.append(f"• fp <code>{h(fp[:10])}</code> · {count} акк.: {names}")
    lines += ["", "Откройте карточку пользователя, чтобы отметить его доверенным (снять флаг твинка)."]
    return "\n".join(lines)


def user_not_found(query: str) -> str:
    return f"Пользователь «{h(query)}» не найден."


def user_ledger(user: User, entries: Sequence[LedgerEntry], page: int, total: int, page_size: int) -> str:
    lines = [f"📜 Леджер <b>{h(user.display_name)}</b> (<code>{user.id}</code>)", ""]
    if not entries:
        lines.append("Операций нет.")
    for entry in entries:
        lines.append(
            f"{fmt_signed(entry.amount)} · {h(LEDGER_KIND_LABELS.get(entry.kind, entry.kind))}"
            f"{' · ' + h(entry.reference) if entry.reference else ''}\n"
            f"   <i>{fmt_dt(entry.created_at)}</i> → {entry.balance_after}"
        )
    pages = max((total + page_size - 1) // page_size, 1)
    lines += ["", f"Стр. {page + 1}/{pages} · всего {total}"]
    return "\n".join(lines)


def user_refs(user: User, refs: Sequence[User]) -> str:
    lines = [f"👥 Рефералы L1 <b>{h(user.display_name)}</b>", ""]
    if not refs:
        lines.append("Нет рефералов.")
    for ref in refs:
        mark = "✅" if ref.referral_activated else "⏳"
        lines.append(
            f"{mark} <code>{ref.id}</code> {h(ref.display_name)} · акт. {ref.activity_score} · "
            f"{fmt_ago(ref.created_at)}"
        )
    return "\n".join(lines)


def user_adjust_prompt(user: User, balance: int) -> str:
    return (
        f"Баланс {h(user.display_name)}: <b>{balance} {STAR}</b>\n\n"
        "Отправьте сумму со знаком и комментарий, например:\n"
        "<code>+50 бонус за конкурс</code>\n<code>-20 накрутка</code>"
    )


def user_note_prompt(user: User) -> str:
    current = f"\nТекущая: <i>{h(user.admin_note)}</i>" if user.admin_note else ""
    return f"Заметка для <code>{user.id}</code>. Отправьте текст (или «-» чтобы удалить).{current}"


def user_message_prompt(user: User) -> str:
    return f"Сообщение пользователю {h(user.display_name)} (<code>{user.id}</code>). Отправьте текст."


def user_ban_prompt(user: User) -> str:
    return f"Причина бана для <code>{user.id}</code> {h(user.display_name)}:"


def fraud_events(
    items: Sequence[FraudEvent], page: int, total: int, page_size: int, user: User | None
) -> str:
    title = "🕵️ <b>Антифрод-события</b>" + (f" · <code>{user.id}</code>" if user else "")
    lines = [title, ""]
    if not items:
        lines.append("Событий нет.")
    for item in items:
        lines.append(
            f"• <code>{item.user_id}</code> <b>{h(item.kind)}</b> {h(item.detail[:80])}\n"
            f"   <i>{fmt_dt(item.created_at)}</i>"
        )
    pages = max((total + page_size - 1) // page_size, 1)
    lines += ["", f"Стр. {page + 1}/{pages} · всего {total}"]
    return "\n".join(lines)


def suspicious(rows: Sequence[tuple[User, int, int]]) -> str:
    lines = [
        "🕵️ <b>Подозрительные рефереры</b>",
        "",
        "≥5 рефералов L1, отсортировано по низкой доле активации.",
        "",
    ]
    if not rows:
        lines.append("Пока никого.")
    for user, total, act in rows:
        ratio = act * 100 // total if total else 0
        flag = "🔴" if ratio < 20 else "🟡" if ratio < 50 else "🟢"
        lines.append(f"{flag} <code>{user.id}</code> {h(user.display_name)} · {act}/{total} ({ratio}%)")
    return "\n".join(lines)


# --- withdrawals --------------------------------------------------------------------


def withdrawals_home(counts: dict[str, int]) -> str:
    return (
        "💸 <b>Выводы</b>\n\n"
        f"Ожидают: <b>{counts.get('pending_count', 0)}</b> ({counts.get('pending_sum', 0)} {STAR})\n"
        f"Согласованы, ждут отправки: <b>{counts.get('approved_manual_count', 0)}</b> "
        f"({counts.get('approved_manual_sum', 0)} {STAR})\n"
        f"Выплачено: {counts.get('sent_count', 0)} ({counts.get('sent_sum', 0)} {STAR}) · "
        f"отклонено {counts.get('rejected_count', 0)} · отменено {counts.get('cancelled_count', 0)}\n\n"
        "Порядок: «Согласовать» → отправить Stars вручную (подарок Stars) → «Подтвердить отправку»."
    )


def withdrawals_list(
    items: Sequence[Withdrawal], filter_name: str, page: int, total: int, page_size: int
) -> str:
    titles = {
        "open": "Очередь (ожидают + согласованы)",
        "pending": "Ожидают",
        "approved": "Согласованы — ждут отправки",
        "history": "История",
    }
    lines = [f"💸 <b>{titles.get(filter_name, filter_name)}</b>", ""]
    if not items:
        lines.append("Пусто.")
    pages = max((total + page_size - 1) // page_size, 1)
    lines.append(f"Стр. {page + 1}/{pages} · всего {total}")
    return "\n".join(lines)


def withdrawal_card(
    wd: Withdrawal,
    user: User | None,
    balance: int,
    refs: dict[int, int],
    activated: int,
    sent_before: int,
    fraud_count: int,
    linked: Sequence[User] = (),
) -> str:
    name = h(user.display_name) if user else str(wd.user_id)
    lines = [
        f"💸 <b>Заявка #{wd.id}</b> · {WITHDRAWAL_STATUS_LABELS.get(wd.status, wd.status)}",
        "",
        f"Пользователь: {name} (<code>{wd.user_id}</code>) {mention(wd.user_id, '↗')}",
        f"Сумма: <b>{h(wd.gift_label)}</b>",
        *([f"Комиссия: {wd.fee} {STAR}"] if wd.fee else []),
        f"Создана: {fmt_dt(wd.created_at)} ({fmt_ago(wd.created_at)})",
    ]
    if wd.gift_id:
        lines.append(f"Подарок: <code>{h(wd.gift_id)}</code>")
    if user is not None:
        lines += [
            "",
            f"Остаток баланса: {balance} {STAR} · уровень {user.level} · активность {user.activity_score}",
            f"Рефералы L1/L2: {refs.get(1, 0)}/{refs.get(2, 0)} · активных {activated}",
            f"Выплачено ранее: {sent_before} {STAR} · фрод-событий: {fraud_count}",
            f"Регистрация: {fmt_dt(user.created_at, with_time=False)} · "
            f"{'Premium' if user.is_premium else 'без Premium'}",
        ]
        if user.is_banned:
            lines.append("🚫 Пользователь в бане!")
        if user.device_verified_at is None:
            lines.append("🛡 Устройство не подтверждено")
        if linked and not user.is_trusted:
            others = ", ".join(f"<code>{item.id}</code>" for item in linked[:5])
            lines.append(f"👯 <b>Твинк!</b> То же устройство у: {others}")
        elif user.is_trusted:
            lines.append("🤝 Доверенный пользователь")
    if wd.reviewed_by:
        lines += ["", f"Обработал: <code>{wd.reviewed_by}</code> {fmt_dt(wd.reviewed_at)}"]
    if wd.sent_at:
        lines.append(f"Отправлено: {fmt_dt(wd.sent_at)}")
    if wd.admin_note:
        lines += ["", f"📝 {h(wd.admin_note)}"]
    if wd.status == "approved_manual":
        if wd.gift_id:
            lines += [
                "",
                "➡️ Нажмите «Отправить подарок» — бот спишет Stars со своего баланса "
                "и отправит подарок пользователю. Или отметьте, что уже отправили вручную.",
            ]
        else:
            lines += [
                "",
                "➡️ Отправьте пользователю Stars вручную (подарок Stars из личного аккаунта), "
                "затем нажмите «Подтвердить отправку».",
            ]
    return "\n".join(lines)


def withdrawal_alert(wd: Withdrawal, user: User, balance: int, refs: dict[int, int], activated: int) -> str:
    return (
        f"🔔 <b>Новая заявка на вывод #{wd.id}</b>\n\n"
        f"{h(user.display_name)} (<code>{user.id}</code>) {mention(user.id, '↗')}\n"
        f"Подарок: <b>{h(wd.gift_label)}</b> · остаток {balance} {STAR}\n"
        f"Уровень {user.level} · активность {user.activity_score} · "
        f"рефералы {refs.get(1, 0)} (акт. {activated})\n"
        f"Регистрация {fmt_dt(user.created_at, with_time=False)}"
    )


def withdrawal_cancelled_alert(wd: Withdrawal, name: str) -> str:
    return f"↩️ Заявка #{wd.id} на {h(wd.gift_label)} отменена пользователем {h(name)}."


def payout_log_post(wd: Withdrawal, user: User) -> str:
    """Public channel post when a withdrawal is marked sent."""
    uname = f"@{user.username}" if user.username else "без @username"
    return (
        f"💸 <b>Выплата #{wd.id}</b>\n"
        f"{h(user.display_name)} · {uname} · <code>{user.id}</code>\n"
        f"{h(wd.gift_label)}"
    )


def reject_reason_prompt(wd: Withdrawal) -> str:
    return (
        f"Причина отклонения заявки #{wd.id} ({h(wd.gift_label)}). "
        "Пользователь увидит её в уведомлении. Отправьте текст."
    )


# --- broadcast ----------------------------------------------------------------------


def broadcast_home(history: Sequence[Broadcast], running: Broadcast | None) -> str:
    lines = ["📣 <b>Рассылка</b>", ""]
    if running is not None:
        lines += [f"Сейчас идёт рассылка #{running.id}: {running.sent}/{running.total}", ""]
    lines.append("Нажмите «Новая рассылка» и отправьте сообщение любого типа (текст, фото, видео…).")
    if history:
        lines += ["", "Последние:"]
        for item in history:
            lines.append(
                f"• #{item.id} {broadcast_status_icon(item.status)} {item.sent}/{item.total} · "
                f"{BROADCAST_AUDIENCE_LABELS.get(item.audience, item.audience)} · {fmt_ago(item.created_at)}"
            )
    return "\n".join(lines)


def broadcast_status_icon(status: str) -> str:
    return {
        "pending": "⏳",
        "running": "▶️",
        "done": "✅",
        "cancelled": "⏹",
        "failed": "❌",
    }.get(status, status)


def broadcast_prompt() -> str:
    return (
        "📣 Отправьте сообщение для рассылки.\n"
        "Подойдёт любой тип: текст с форматированием, фото, видео, GIF, документ. "
        "Оно будет скопировано пользователям как есть."
    )


def broadcast_button_prompt() -> str:
    return (
        "Добавить кнопку-ссылку под сообщением?\n"
        "Отправьте в формате <code>Текст кнопки | https://ссылка</code> или нажмите «Без кнопки»."
    )


def broadcast_audience_prompt(sizes: dict[str, int]) -> str:
    lines = ["Кому отправить?", ""]
    for key, label in BROADCAST_AUDIENCE_LABELS.items():
        lines.append(f"• {label}: {sizes.get(key, 0)}")
    return "\n".join(lines)


def broadcast_confirm(audience: str, size: int, button_text: str | None) -> str:
    btn = f"\nКнопка: «{h(button_text)}»" if button_text else "\nБез кнопки"
    return (
        "Проверьте превью выше.\n\n"
        f"Аудитория: <b>{BROADCAST_AUDIENCE_LABELS.get(audience, audience)}</b> — {size} чел.{btn}\n\n"
        "Запустить?"
    )


def broadcast_progress(b: Broadcast) -> str:
    pct = (b.sent + b.failed + b.blocked) * 100 // b.total if b.total else 100
    lines = [
        f"📣 <b>Рассылка #{b.id}</b> {broadcast_status_icon(b.status)} {b.status}",
        "",
        f"Прогресс: {pct}% · отправлено <b>{b.sent}</b> из {b.total}",
        f"Заблокировали бота: {b.blocked} · ошибок: {b.failed}",
        f"Аудитория: {BROADCAST_AUDIENCE_LABELS.get(b.audience, b.audience)}",
    ]
    if b.started_at:
        lines.append(f"Старт: {fmt_dt(b.started_at)}")
    if b.finished_at:
        lines.append(f"Финиш: {fmt_dt(b.finished_at)}")
    if b.error:
        lines.append(f"Ошибка: {h(b.error)}")
    return "\n".join(lines)


# --- catalog ------------------------------------------------------------------------


def tasks_home(tasks: Sequence[Task], completions: dict[int, int]) -> str:
    lines = ["📋 <b>Задания</b>", ""]
    if not tasks:
        lines.append("Заданий нет. Создайте первое.")
    for task in tasks:
        state = "🟢" if task.is_active else "⚪"
        lines.append(
            f"{state} #{task.id} <b>{h(task.title)}</b> · +{task.reward} {STAR} · "
            f"{TASK_KIND_LABELS.get(task.kind, task.kind)} · выполнено {completions.get(task.id, 0)}"
        )
    return "\n".join(lines)


def task_card(task: Task, completions: int) -> str:
    return (
        f"📌 <b>{h(task.title)}</b> (#{task.id}) {'🟢 активно' if task.is_active else '⚪ выключено'}\n\n"
        f"{h(task.description) or '<i>без описания</i>'}\n\n"
        f"Тип: {TASK_KIND_LABELS.get(task.kind, task.kind)}\n"
        f"Условие: {h(task_target(task)) or '—'}\n"
        f"Награда: {task.reward} {STAR} · порядок {task.sort_order}\n"
        f"Выполнили: {completions}\n"
        f"slug: <code>{h(task.slug)}</code>"
    )


def task_new_kind() -> str:
    return "Тип нового задания:"


def task_new_title() -> str:
    return "Название задания (до 128 символов):"


def task_new_desc() -> str:
    return "Описание (или «-» чтобы пропустить):"


def task_new_reward() -> str:
    return "Награда в Stars (целое число ≥ 1):"


def task_new_target(kind: str) -> str:
    return {
        "subscribe": "Канал для подписки: <code>@username</code> или для приватного/платного канала "
        "<code>-100…|https://t.me/+ссылка|Название</code>. "
        "Бот должен быть админом канала, чтобы проверять подписку.",
        "invite": "Сколько активных рефералов нужно (число):",
        "streak": "Какая серия ежедневок нужна (дней):",
        "custom": "Ссылка для перехода (https://…) или «-» без ссылки:",
    }.get(kind, "Параметр задания:")


def boosts_home(products: Sequence[BoostProduct], sales: dict[int, int]) -> str:
    lines = ["🚀 <b>Бусты</b>", ""]
    if not products:
        lines.append("Бустов нет.")
    for product in products:
        state = "🟢" if product.is_active else "⚪"
        lines.append(
            f"{state} #{product.id} <b>{h(product.title)}</b> · {product.xtr_price} XTR · "
            f"{boost_detail(product)} · продаж {sales.get(product.id, 0)}"
        )
    return "\n".join(lines)


def boost_detail(product: BoostProduct) -> str:
    return describe_boost(product)


def boost_card(product: BoostProduct, sales: int) -> str:
    return (
        f"🚀 <b>{h(product.title)}</b> (#{product.id}) "
        f"{'🟢 активен' if product.is_active else '⚪ выключен'}\n\n"
        f"{h(product.description) or '<i>без описания</i>'}\n\n"
        f"Тип: {boost_detail(product)}\nЦена: {product.xtr_price} XTR\nПродаж: {sales}\n"
        f"slug: <code>{h(product.slug)}</code>"
    )


def boost_new_kind() -> str:
    return "Тип нового буста:"


def boost_new_title() -> str:
    return "Название буста:"


def boost_new_desc() -> str:
    return "Описание (или «-»):"


def boost_new_price() -> str:
    return "Цена в XTR (целое число ≥ 1):"


def boost_new_param(kind: str) -> str:
    if kind == BoostKind.STARS_PACK.value:
        return "Сколько внутренних Stars начислять за покупку:"
    return "Множитель и длительность через пробел, например <code>2 24</code> (×2 на 24 часа):"


def edit_prompt(field_label: str, current: Any) -> str:
    return f"Новое значение — {field_label}.\nТекущее: <code>{h(current)}</code>"


# --- promo --------------------------------------------------------------------------


def promo_home(items: Sequence[PromoCode], page: int, total: int, page_size: int) -> str:
    lines = ["🎟 <b>Промокоды</b>", ""]
    if not items:
        lines.append("Промокодов нет.")
    for promo in items:
        state = "🟢" if promo.is_active else "⚪"
        limit = f"{promo.uses}/{promo.max_uses}" if promo.max_uses else f"{promo.uses}/∞"
        exp = f" · до {fmt_dt(promo.expires_at, with_time=False)}" if promo.expires_at else ""
        lines.append(f"{state} <code>{h(promo.code)}</code> · +{promo.reward} {STAR} · {limit}{exp}")
    pages = max((total + page_size - 1) // page_size, 1)
    lines += ["", f"Стр. {page + 1}/{pages}"]
    return "\n".join(lines)


def promo_card(promo: PromoCode, *, bot_username: str = "") -> str:
    limit = str(promo.max_uses) if promo.max_uses else "без лимита"
    lines = [
        f"🎟 <code>{h(promo.code)}</code> {'🟢 активен' if promo.is_active else '⚪ выключен'}",
        "",
        f"Награда: {promo.reward} {STAR}",
        f"Активаций: {promo.uses} · лимит {limit}",
        f"Действует до: {fmt_dt(promo.expires_at) if promo.expires_at else 'бессрочно'}",
        f"Создан: {fmt_dt(promo.created_at)}",
    ]
    if bot_username:
        link = activation_link(bot_username, promo.code)
        lines += [
            "",
            "<b>Код:</b> <code>" + h(promo.code) + "</code>",
            f"<b>Ссылка-активатор:</b>\n<code>{h(link)}</code>",
            "",
            "Для рассылки укажите кнопку:",
            f"<code>Активировать | {h(link)}</code>",
        ]
    return "\n".join(lines)


def promo_new_code() -> str:
    return "Код промокода (латиница/цифры, 3–32 символа) или «auto» для случайного:"


def promo_new_reward() -> str:
    return "Награда в Stars:"


def promo_new_limit() -> str:
    return "Лимит активаций (0 — без лимита):"


def promo_new_days() -> str:
    return "Срок действия в днях (0 — бессрочно):"


def promo_broadcast_prompt(promo: PromoCode, link: str) -> str:
    return (
        f"📣 Рассылка промокода <code>{h(promo.code)}</code> (+{promo.reward} {STAR})\n\n"
        f"Кнопка уже будет: <b>Активировать</b> → {h(link)}\n\n"
        "Отправьте сообщение рассылки (текст / фото / видео…) — дальше выберете аудиторию."
    )


# --- payments -----------------------------------------------------------------------


def payments_home(
    items: Sequence[Payment], titles: dict[int, str], page: int, total: int, page_size: int, revenue: int
) -> str:
    lines = ["💳 <b>Платежи</b>", "", f"Выручка (без возвратов): <b>{revenue} XTR</b>", ""]
    if not items:
        lines.append("Платежей нет.")
    for item in items:
        icon = "↩️" if item.status == "refunded" else "✅"
        lines.append(
            f"{icon} #{item.id} · {item.xtr_amount} XTR · {h(titles.get(item.product_id or 0, '—'))} · "
            f"<code>{item.user_id}</code> · {fmt_ago(item.created_at)}"
        )
    pages = max((total + page_size - 1) // page_size, 1)
    lines += ["", f"Стр. {page + 1}/{pages} · всего {total}"]
    return "\n".join(lines)


def payment_card(payment: Payment, title: str, user: User | None) -> str:
    who = f"{h(user.display_name)} (<code>{user.id}</code>)" if user else f"<code>{payment.user_id}</code>"
    lines = [
        f"💳 <b>Платёж #{payment.id}</b> · {'↩️ возвращён' if payment.status == 'refunded' else '✅ оплачен'}",
        "",
        f"Пользователь: {who}",
        f"Товар: {h(title)}",
        f"Сумма: <b>{payment.xtr_amount} XTR</b>",
        f"Чек: <code>{h(payment.telegram_charge_id)}</code>",
        f"Дата: {fmt_dt(payment.created_at)}",
    ]
    if payment.refunded_at:
        lines.append(f"Возврат: {fmt_dt(payment.refunded_at)} админом <code>{payment.refunded_by}</code>")
    return "\n".join(lines)


def refund_confirm(payment: Payment, title: str) -> str:
    return (
        f"Вернуть <b>{payment.xtr_amount} XTR</b> за «{h(title)}» пользователю "
        f"<code>{payment.user_id}</code>?\n\n"
        "Начисленные Stars будут списаны (баланс может уйти в минус), множитель — отключён."
    )


# --- settings / providers / channels / admins -----------------------------------------


def settings_home(effective: Settings, overrides: dict[str, Any]) -> str:
    overridden = sum(1 for key in RUNTIME_OVERRIDABLE if key in overrides)
    lines = [
        "⚙️ <b>Настройки</b>",
        "",
        "Выберите раздел. Значения применяются сразу, без перезапуска.",
        f"Переопределено в БД: <b>{overridden}</b> из {len(RUNTIME_OVERRIDABLE)}.",
    ]
    return "\n".join(lines)


def settings_group(group_id: str, effective: Settings, overrides: dict[str, Any]) -> str:
    title = SETTINGS_GROUP_LABELS.get(group_id, group_id)
    keys = SETTINGS_GROUPS.get(group_id, ())
    lines = [
        f"⚙️ <b>{h(title)}</b>",
        "",
        "✏️ — переопределено в БД (не из .env).",
        "",
    ]
    for key in keys:
        if key not in RUNTIME_OVERRIDABLE:
            continue
        mark = "✏️ " if key in overrides else ""
        lines.append(
            f"{mark}<b>{h(RUNTIME_SETTING_LABELS.get(key, key))}</b>: "
            f"<code>{h(format_value(getattr(effective, key)))}</code>"
        )
    return "\n".join(lines)


def setting_prompt(key: str, current: Any, default: Any, overridden: bool) -> str:
    kind = RUNTIME_OVERRIDABLE[key]
    hint = "вкл / выкл" if kind is bool else "целое число" if kind is int else "текст"
    if key == "currency_emoji_id":
        hint = "вставьте премиум-эмодзи из Telegram (или numeric id / <tg-emoji>…)"
    elif key == "currency_emoji_fallback":
        hint = "вставьте премиум-эмодзи или unicode (например ⭐); id подтянется из entity"
    return (
        f"⚙️ <b>{h(RUNTIME_SETTING_LABELS.get(key, key))}</b>\n"
        f"Ключ: <code>{key}</code>\n\n"
        f"Сейчас: <code>{h(format_value(current))}</code>"
        f"{' (переопределено)' if overridden else ''}\n"
        f"Из .env: <code>{h(format_value(default))}</code>\n\n"
        f"Отправьте новое значение ({hint})."
    )


def _member_check_url(settings: Settings) -> str:
    if settings.web_public_url.strip():
        return settings.web_url("/api/tgrass/member")
    return "/api/tgrass/member"


def providers_home(states: dict[str, bool], configured: dict[str, bool], settings: Settings) -> str:
    lines = [
        "🔒 <b>Провайдеры ОП</b>",
        "",
        "Порядок для пользователя:",
        "• проверка устройства пройдена → <b>PiarFlow</b>, затем <b>Tgrass</b>;",
        "• не пройдена → только <b>Tgrass</b>.",
        "Ошибки API — fail-open (не блокируют пользователей).",
        "",
        "Вебхуки отписок:",
        "• PiarFlow: <code>/api/piarflow/webhook</code>",
        "• Tgrass: <code>/api/tgrass/unsubscribe</code> (задания: <code>/api/tgrass/webhook</code>)",
        "",
        "Закупка Tgrass — «Проверка подписки»:",
        f"• URL: <code>{h(_member_check_url(settings))}</code>",
        "• <code>is_member: true</code> только после прохождения ОП "
        "(старт бота сам по себе не считается).",
        f"• API key (<code>TGRASS_MEMBER_KEY</code>): "
        f"{'задан' if settings.tgrass_member_key.strip() else 'не задан'}",
        "",
        "Статистика выданных и засчитанных спонсоров PiarFlow — кнопки ниже.",
        "",
    ]
    for name in CASCADE:
        state = "🟢 ВКЛ" if states.get(name) else "⚪ ВЫКЛ"
        conf = "ключ задан" if configured.get(name) else "не настроен (skip)"
        title = PROVIDER_TITLES[name]
        docs = PROVIDER_DOCS.get(name)
        label = f'<a href="{docs}">{title}</a>' if docs else title
        lines.append(f"{state} · <b>{label}</b> · {conf}")
    return "\n".join(lines)


def admins_home(owners: Sequence[int], admins: Sequence[Admin], names: dict[int, str]) -> str:
    lines = ["🛡 <b>Администраторы</b>", "", "Владельцы (ADMIN_IDS в .env, не редактируются):"]
    for uid in sorted(owners):
        lines.append(f"• <code>{uid}</code> {h(names.get(uid, ''))}")
    lines += ["", "Админы (управляются здесь):"]
    if not admins:
        lines.append("— нет —")
    for row in admins:
        lines.append(
            f"• <code>{row.user_id}</code> {h(names.get(row.user_id, ''))} · добавил {row.added_by} · "
            f"{fmt_dt(row.created_at, with_time=False)}"
        )
    return "\n".join(lines)


def admin_add_prompt() -> str:
    return "Отправьте Telegram ID нового администратора (пользователь должен был запускать бота)."


# --- audit / data -------------------------------------------------------------------


def audit(items: Sequence[AdminAction], page: int, total: int, page_size: int) -> str:
    lines = ["🧾 <b>Журнал действий</b>", ""]
    if not items:
        lines.append("Пусто.")
    for item in items:
        target = f" → {h(item.target_type)} {h(item.target_id)}" if item.target_id else ""
        detail = ""
        if item.detail:
            detail = " · " + ", ".join(f"{h(k)}={h(v)}" for k, v in list(item.detail.items())[:3])
        lines.append(
            f"• <code>{item.admin_id}</code> {h(action_label(item.action))}{target}{detail}\n"
            f"   <i>{fmt_dt(item.created_at)}</i>"
        )
    pages = max((total + page_size - 1) // page_size, 1)
    lines += ["", f"Стр. {page + 1}/{pages} · всего {total}"]
    return "\n".join(lines)


def data_home() -> str:
    return (
        "🗂 <b>Данные</b>\n\n"
        "Экспорт в CSV (UTF-8, открывается в Excel) — до 50 000 строк на файл.\n"
        "Импорт: CSV с заголовком <code>id,username</code> — создаёт пользователей без экономики."
    )


def import_prompt() -> str:
    return (
        "Пришлите CSV-файл следующим сообщением.\nФормат: <code>id,username</code> (UTF-8, username без @)."
    )


def import_need_csv() -> str:
    return "Нужен документ с расширением .csv (заголовок id,username)."


def import_result(created: int, updated: int, unchanged: int, errors: int, error_lines: list[str]) -> str:
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
        lines.extend(h(line) for line in error_lines[:10])
    return "\n".join(lines)


def no_access() -> str:
    return "Недостаточно прав."


def ambassadors_hub(pending: int, approved: int) -> str:
    return (
        "🤝 <b>Амбассадоры</b>\n\n"
        f"На проверке: <b>{pending}</b>\n"
        f"Одобрено: <b>{approved}</b>"
    )


def ambassadors_empty(kind: str) -> str:
    return f"Список «{h(kind)}» пуст."


def ambassador_card(slot: AmbassadorSlot, owner_name: str = "") -> str:
    kind = AMBASSADOR_KIND_LABELS.get(slot.kind, slot.kind)
    status = AMBASSADOR_STATUS_LABELS.get(slot.status, slot.status)
    who = h(owner_name) if owner_name else str(slot.user_id)
    lines = [
        f"🤝 <b>#{slot.id} {h(slot.title)}</b> · {kind}",
        f"Статус: <b>{status}</b>",
        f"Владелец: {who} (<code>{slot.user_id}</code>)",
        f"Ссылка: {h(slot.invite_link)}",
    ]
    if slot.chat_id:
        lines.append(f"chat_id: <code>{slot.chat_id}</code>")
    if slot.status == AmbassadorStatus.APPROVED.value:
        lines += [
            "",
            f"L1: {slot.l1_bonus} ⭐ / {slot.l1_percent}%",
            f"L2: {slot.l2_bonus} ⭐ / {slot.l2_percent}%",
            f"Промо: {slot.promo_reward} ⭐ · лимит {slot.promo_max_uses or '∞'}",
            f"Автопост: {'да' if slot.promo_auto_post else 'нет'}",
        ]
    if slot.reject_reason:
        lines += ["", f"Причина: {h(slot.reject_reason)}"]
    return "\n".join(lines)


def amb_ask_l1_bonus() -> str:
    return "L1 бонус за активацию реферала (⭐, целое ≥ 0):"


def amb_ask_l1_percent() -> str:
    return "L1 процент с заработка реферала (0–100):"


def amb_ask_l2_bonus() -> str:
    return "L2 бонус (⭐):"


def amb_ask_l2_percent() -> str:
    return "L2 процент (0–100):"


def amb_ask_promo_reward() -> str:
    return "Награда дневного промокода (⭐, ≥ 1):"


def amb_ask_promo_max_uses() -> str:
    return "Лимит активаций промокода (0 = без лимита):"


def amb_ask_reject() -> str:
    return "Причина отклонения:"


def amb_ask_chat_id() -> str:
    return "Numeric chat_id канала/чата (после добавления бота админом):"
