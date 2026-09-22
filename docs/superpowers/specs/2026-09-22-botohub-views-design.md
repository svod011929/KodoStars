# KodoStars — BotoHub Views (показы рекламы)

Дата: 2026-09-22. Согласовано с Daniel: триггеры C (hi + earn), runtime включая токен (C), кулдаун runtime (C), архитектура тонкий сервис + hooks (1).

## Цель

Интеграция [BotoHub Views](https://views.botohub.me/integration): бот заказывает показ рекламы пользователю через `POST /ad/SendPost`. Это **не** ОП и не меняет каскад PiarFlow.

## API

- URL по умолчанию: `https://views.botohub.me/ad/SendPost`
- Headers: `Authorization: <token>` (**без** Bearer), `Content-Type: application/json`
- Body: `{ "SendToChatId": <tg_id>, "hi": <bool> }`
- Успех: `SendPostResult == 1`. Остальные коды / сеть — fail-open (лог).

Правила провайдера:

- `hi: true` только после `/start`, лучше только новым; лимит 24h на стороне BotoHub.
- Обычные показы — только после полезного действия (не `/start`).

## Поведение

| Событие | Действие |
| --- | --- |
| Первый `/start` (`first_start`), пользователь дошёл до home | `maybe_send_hi` |
| Успешная ежедневка / зачёт задания / активация промо | `maybe_send_ad` |

- Вызов fire-and-forget (`asyncio.create_task`) после ответа пользователю, без DB session.
- Обычные показы: per-user in-memory кулдаун (`botohub_views_cooldown_seconds`, дефолт 60).
- `hi` кулдаун не учитывает.
- `enabled=false` или пустой token → no-op.

## Конфиг (runtime + `.env` defaults)

| Ключ | Тип | Дефолт |
| --- | --- | --- |
| `botohub_views_enabled` | bool | `false` |
| `botohub_views_token` | str | `""` |
| `botohub_views_cooldown_seconds` | int | `60` |
| `botohub_views_api_url` | str | `https://views.botohub.me/ad/SendPost` |

Все четыре в `RUNTIME_OVERRIDABLE` → **Админка → Настройки**.

## Компоненты

- `app/services/botohub_views.py` — клиент + кулдаун + schedule helpers.
- Hooks: `handlers/start.py`, `earn.py`, `promo.py`.
- HTTP: `app.op.http.post_json`.
- Миграций нет.

## Тесты

Unit с mock `post_json`: disabled/no token, success, fail-open, cooldown vs hi, payload `hi` flag.
