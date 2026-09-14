<!-- kododrive-readme-style -->

<div align="center">
  <img src="./assets/readme-header.svg" width="100%" alt="KodoStars" />
</div>

<br/>

<div align="center">
  <img src="./assets/readme-meta.svg" width="100%" alt="meta" />
</div>

<br/>

<p align="center">
  <a href="https://github.com/svod011929/KodoStars"><img src="https://img.shields.io/badge/GitHub-KodoStars-0D1117?style=for-the-badge&logo=github&logoColor=34D399" alt="repo" /></a>
  <a href="https://t.me/gveom"><img src="https://img.shields.io/badge/Telegram-@gveom-26A5E4?style=for-the-badge&logo=telegram&logoColor=white" alt="tg" /></a>
  <a href="https://github.com/svod011929"><img src="https://img.shields.io/badge/Author-svod011929-7C3AED?style=for-the-badge&logo=github&logoColor=white" alt="author" /></a>
</p>

<!-- /kododrive-readme-style -->

# KodoStars

Telegram-бот на **Python 3.12 / aiogram 3**: реферальная экономика на внутренних Stars, ежедневки, задания, бусты за **Telegram Stars (XTR)** и очередь выводов. Монетизация трафика — каскад обязательной подписки (ОП): **Flyer → SubGram → BotoHub → PiarFlow → TGrass → manual**.

Интерфейс — русский. Выплаты пользователям — **только Telegram Stars**. CryptoBot нет.

Автор: [KodoDrive](https://github.com/svod011929)

## Возможности

- `/start` и deep-link `ref_<tg_id>`
- Многоуровневые рефералы (по умолчанию 2), антифрод: бонус после минимальной активности
- Ежедневная серия, задания, уровни с множителями
- Покупка бустов через `sendInvoice` с валютой `XTR`
- Заявки на вывод → админ согласовывает → подтверждает ручную отправку Stars
- Админка: статистика, очередь выводов, тумблеры провайдеров, рассылка, бан
- Каскад ОП за одним `OpGate`: ключ не задан → skip, ошибка API → fail-open

## Стек

- aiogram 3.x, asyncio
- SQLAlchemy 2 + aiosqlite (SQLite MVP, URL готов к Postgres)
- pydantic-settings, structlog
- `create_all` при старте (для продакшена с Postgres подключите Alembic)

## Установка

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Заполните `BOT_TOKEN` (BotFather) и `ADMIN_IDS` (ваши Telegram ID через запятую).

## Запуск

```bash
python -m app
```

Точка входа поднимает БД, сидирует каталог и стартует long polling. С плейсхолдер-токеном процесс тоже запускает polling — Telegram API ответит ошибкой авторизации, это ожидаемо.

## Переменные окружения

См. `.env.example`. Основные группы:

| Группа | Ключи |
| --- | --- |
| Telegram | `BOT_TOKEN`, `ADMIN_IDS` |
| БД | `DATABASE_URL` (`sqlite+aiosqlite:///./data/kodostars.db` или `postgresql+asyncpg://…`) |
| Экономика | `REFERRAL_LEVELS`, проценты/бонусы L1/L2, `MIN_REFERRAL_ACTIVITY`, ежедневка, `WITHDRAW_MIN` |
| Flyer | `FLYER_ENABLED`, `FLYER_API_KEY`, `FLYER_API_URL` |
| SubGram | `SUBGRAM_ENABLED`, `SUBGRAM_API_KEY`, `SUBGRAM_API_URL` |
| BotoHub | `BOTOHUB_ENABLED`, `BOTOHUB_API_KEY`, `BOTOHUB_API_URL`, `BOTOHUB_BOT_ID` |
| PiarFlow | `PIARFLOW_ENABLED`, `PIARFLOW_API_KEY`, `PIARFLOW_API_URL` |
| TGrass | `TGRASS_ENABLED`, `TGRASS_API_KEY`, `TGRASS_API_URL`, `TGRASS_CHANNELS` |
| Manual | `MANUAL_ENABLED`, `MANUAL_OP_CHANNELS` (`@channel` или `-100…`) |

Провайдер без ключа не блокирует пользователей. Админ может выключить провайдера в рантайме (таблица `provider_states`).

## Как добавить OP-провайдера

1. Создайте `app/op/myprovider.py` с классом-адаптером:
   - `name: str`
   - `async def check(user) -> OpResult`
   - `async def verify(user) -> OpResult` (кнопка «Я подписался»)
2. Если нет ключа — `OpResult.skip(...)`.
   Если API упал — `OpResult.fail_open_result(...)`.
   Если есть невыполненные спонсоры — `OpResult.blocked(name, sponsors)`.
3. Зарегистрируйте адаптер в `default_adapters()` и имя в `CASCADE` / `PROVIDER_NAMES` (`app/op/gate.py`, `app/db/seed.py`).
4. Добавьте `*_ENABLED` и ключи в `app/config.py` и `.env.example`.

Контракты текущих адаптеров:

- **Flyer** — `POST https://api.flyerservice.io/check` (`key`, `user_id`) и `get_tasks`
- **SubGram** — `POST /get-sponsors`, проверка `POST /get-user-subscriptions`, заголовок `Auth`
- **BotoHub** — `POST {BOTOHUB_API_URL}/sponsors` и `/sponsors/check` (Bearer / X-API-Key). Базовый URL кабинета можно переопределить
- **PiarFlow** — `POST https://piarflow.com/v1/sponsors` и `/sponsors/check`, `Authorization: Bearer`
- **TGrass** — HTTP `/check` при наличии ключа + `getChatMember` по `TGRASS_CHANNELS`
- **manual** — только `getChatMember` по `MANUAL_OP_CHANNELS`

## Вывод Stars

Bot API **не умеет** перевести произвольное число Stars с баланса бота на пользователя. `sendInvoice` / `refundStarPayment` — это приём и возврат оплаты боту, не выплата. `sendGift` отправляет подарок, а не сумму XTR из заявки.

Поэтому очередь такая:

1. Пользователь создаёт заявку (баланс не списывается).
2. Админ нажимает **Согласовать** → статус `approved_manual`, в карточке инструкция.
3. Админ отправляет Stars вручную (подарок Stars с личного аккаунта или ваш согласованный канал).
4. Админ жмёт **Подтвердить отправку** → статус `sent`, леджер дебетуется.

Не подтверждайте отправку, пока Stars реально не ушли.

## Тесты

```bash
pytest
```

Покрыты леджер (credit/debit/баланс) и атрибуция рефералов (уровни, самореферал, порог активности, доля с заработка), плюс каскад OpGate.

## Структура

```
app/
  __main__.py          # python -m app
  config.py
  bot/handlers/        # пользователь + админ
  bot/middlewares/     # сессия, пользователь, OpGate
  services/            # ledger, referrals, daily, tasks, boosts, withdrawals
  op/                  # gate + адаптеры
  db/                  # models, session, seed
tests/
```

---

<!-- kododrive-projects-block -->

## Проекты KodoDrive

Другие проекты автора: [профиль @svod011929](https://github.com/svod011929) · [Telegram](https://t.me/gveom)

### VPN и инфраструктура

- [BuryatVPN — VPN-сервис + Telegram](https://github.com/svod011929/buryatvpn)
- [VPN Server Installer — VLESS + TLS](https://github.com/svod011929/vpn-server-installer)
- [3X-UI Auto Installer](https://github.com/svod011929/3x-ui-auto-installer)
- [AWG Bot Installer — AmneziaWG](https://github.com/svod011929/awg-bot-installer)
- [RemnaShop Installer](https://github.com/svod011929/remnashop-installer)
- [VPN Auto Installer — панели](https://github.com/svod011929/vpn-auto-installer)
- [VPNHubBot — Telegram VPN-бот](https://github.com/svod011929/VPNHubBot)

### Telegram и автоматизация

- [KDS Server Panel — SSH из Telegram](https://github.com/svod011929/KDS_Server_Panel)
- [Telegram → VK Poster](https://github.com/svod011929/telegram-to-vk-poster)
- [KDS Parser CryptoBot](https://github.com/svod011929/kds_parser_cryptobot)
- [Auction Bot](https://github.com/svod011929/auction-bot)
- [Invest Bot](https://github.com/svod011929/invest-bot)
- [Crypto Check Bot](https://github.com/svod011929/crypto-check-bot)
- [KodoRefStarsBot](https://github.com/svod011929/KodoRefStarsBot)
- **KodoStars** ← ты здесь

### Магазины и финансы

- [KodoCashFlow](https://github.com/svod011929/KodoCashFlow)
- [Telegram Crypto Shop](https://github.com/svod011929/telegram-crypto-shop)
- [TalkProfit](https://github.com/svod011929/talkprofit)

### Сайты

- [KodoDrive Portfolio](https://github.com/svod011929/kododrive-portfolio)
- [kododrive.github.io](https://github.com/svod011929/kododrive.github.io)

<!-- /kododrive-projects-block -->
