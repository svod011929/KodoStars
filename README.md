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

Telegram-бот на **Python 3.12 / aiogram 3**: реферальная экономика на внутренних Stars, ежедневки,
задания, промокоды, бусты за **Telegram Stars (XTR)**, очередь выводов с холдом средств и
полноценная **админ-панель внутри Telegram**. Монетизация трафика — каскад обязательной подписки (ОП):
**только PiarFlow** (проверка устройства/твинков до выдачи заданий; вебхук отписок; выплата Stars через Fragment).

Интерфейс — русский. Выплаты пользователям — **только Telegram Stars**. CryptoBot нет.

Автор: [KodoDrive](https://github.com/svod011929)

## Что умеет бот

### Для пользователя

- `/start` и deep-link `ref_<tg_id>`; реферер привязывается **только при первом запуске** (защита от переатрибуции старых аккаунтов)
- Двухуровневая рефералка: бонус за активацию друга + процент с его заработка; уведомления «пришёл новый друг» и «друг активировался: +N ⭐»
- Кнопка **«Поделиться ссылкой»** (`t.me/share/url`) и место в топе рефереров
- Ежедневка с серией, экран-превью «сколько получу сегодня» и таймером до сброса
- Задания: подписка на канал (проверка через `getChatMember`), приглашения, серии, переход по ссылке; автозачёт по событиям
- Уровни (XP → множитель до ×2) с прогресс-баром, бусты-множители и паки Stars за XTR
- Промокоды с лимитом активаций и сроком действия
- Топ по рефералам и по заработку за 7 дней (ники маскируются)
- История операций с пагинацией, список заявок, отмена своей `pending`-заявки
- Вывод: выбор готового подарка Telegram, холд средств, уведомления о каждом изменении статуса
- `/menu`, `/profile`, `/help`, `/terms`, `/paysupport` (обязательные для ботов, принимающих Stars)

### Для администратора (`/admin`)

| Раздел | Возможности |
| --- | --- |
| 📊 Статистика | пользователи всего/сегодня/7д/30д, регистрации по дням, DAU/WAU, баны и блокировки бота, воронка рефералов, экономика по видам начислений, холд, выводы, выручка XTR, **баланс Stars бота** (`getMyStarBalance`), сверка балансов с леджером |
| 👥 Пользователи | поиск по ID/@username, карточка (баланс, холд, уровень, рефералы, платежи, выплаты, фрод), ±баланс с причиной, бан/разбан, заметка, сообщение пользователю, леджер, список рефералов, подозрительные рефереры |
| 💸 Выводы | очередь по статусам с пагинацией, карточка с контекстом пользователя, согласовать / отклонить с причиной / отправить подарок через `sendGift` или подтвердить ручную выплату; карточка новой заявки приходит админам сразу |
| 📣 Рассылка | любой тип контента (`copyMessage`), опциональная URL-кнопка, аудитория (все / активные 7д / активированные), тест себе, фоновая отправка с rate-limit и обработкой `RetryAfter`, прогресс-карточка, остановка |
| 📋 Задания / 🚀 Бусты | мастер создания, редактирование полей, вкл/выкл, удаление (мягкое, если были выполнения/продажи) |
| 🎟 Промокоды | создание (код или `auto`), награда, лимит, срок, вкл/выкл |
| 💳 Платежи | список покупок, карточка, **возврат** через `refundStarPayment` с откатом начисления / отключением буста |
| ⚙️ Настройки | экономика и операционные флаги меняются **без перезапуска** (хранятся в БД, валидируются как `.env`) |
| 🔒 ОП-провайдеры / 📢 Каналы ОП | тумблеры каскада, список своих каналов с проверкой прав бота |
| 🛡 Админы | владельцы из `ADMIN_IDS` добавляют/удаляют админов прямо в боте |
| 🧾 Журнал / 🕵️ Антифрод | аудит всех админ-действий, лента фрод-событий |
| 🗂 Данные | экспорт CSV (пользователи, выводы, леджер, платежи), импорт пользователей CSV |

Режим обслуживания, поддержка и лимиты вывода — тоже переключаются из панели.

## Стек и архитектура

- aiogram 3.x, asyncio, FSM (MemoryStorage)
- SQLAlchemy 2 + aiosqlite (SQLite с WAL по умолчанию) или PostgreSQL (`asyncpg`)
- **Alembic**: миграции применяются автоматически на старте; старая БД, созданная через `create_all`, штампуется базовой ревизией и обновляется
- pydantic-settings (`.env`) + переопределения в таблице `app_settings`
- structlog (JSON или консоль), контекст `update_id`/`user_id` в каждой записи

Ключевые решения:

- **Баланс** — колонка `users.balance`, изменяемая одним атомарным `UPDATE … RETURNING`; леджер — полный журнал с `balance_after`. Гонок при параллельных начислениях нет; есть инструмент сверки.
- **Вывод с холдом**: сумма списывается при создании заявки, возвращается при отклонении/отмене, `confirm_sent` только фиксирует факт выплаты.
- **Платежи идемпотентны** по `telegram_payment_charge_id` — повторная доставка `successful_payment` не начисляет дважды.
- **Доменные события** собираются в сессии и превращаются в уведомления только после `commit` (пользователь никогда не получит сообщение о неслучившемся).
- **Транзакция не пересекает сетевой I/O**: перед каждым вызовом Telegram API (request-middleware бота) и перед каскадом ОП текущая сессия коммитится, поэтому единственный писатель SQLite не блокируется на время HTTP-ожиданий. Апдейты одного пользователя обрабатываются последовательно (`UserLockMiddleware`), разных — параллельно.
- Глобальный обработчик ошибок: пользователю — мягкий ответ, владельцам — трейсбек (с антиспамом).
- Throttle-middleware, трекинг блокировки бота (`my_chat_member`), fail-open для внешних ОП-сервисов.

## Установка

```bash
python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Заполните `BOT_TOKEN` (BotFather) и `ADMIN_IDS` (ваши Telegram ID через запятую). Для платежей
в Stars у бота ничего дополнительно включать не нужно; для проверки подписок добавьте бота
администратором в каналы.

## Запуск

```bash
python -m app
```

Или через Docker:

```bash
docker compose up -d --build
```

На хостинг-панелях (RubyHost / Pterodactyl) укажите `APP PY FILE=main.py` в корне проекта.
Не ставьте `app/__main__.py` — тогда падает `import app` (`ModuleNotFoundError`).

Точка входа: применяет миграции, сидирует каталог заданий/бустов, загружает админов и стартует
long polling. С плейсхолдер-токеном процесс тоже запускается — Telegram ответит ошибкой
авторизации, это ожидаемо.

## Переменные окружения

См. `.env.example`. Основные группы:

| Группа | Ключи |
| --- | --- |
| Telegram | `BOT_TOKEN`, `ADMIN_IDS`, `SUPPORT_CONTACT` |
| Веб / антитвинк | `WEB_PUBLIC_URL`, `SERVER_PORT`, `DEVICE_CHECK_ENABLED`, `DEVICE_CHECK_FOR_WITHDRAW`, `TWINK_BLOCK_REFERRAL`, `TWINK_BLOCK_WITHDRAW`, `TWINK_REQUIRE_IP_MATCH`, `TWINK_IP_WINDOW_DAYS` |
| БД | `DATABASE_URL` (`sqlite+aiosqlite:///./data/kodostars.db` или `postgresql+asyncpg://…`) |
| Экономика | `REFERRAL_LEVELS`, проценты/бонусы L1/L2, `MIN_REFERRAL_ACTIVITY`, `NOTIFY_REFERRER`, ежедневка, `SIGNUP_BONUS`, `CLAIM_COOLDOWN_SECONDS` |
| Вывод | `WITHDRAW_ENABLED`, `WITHDRAW_MIN`, `WITHDRAW_MAX`, `WITHDRAW_COOLDOWN_HOURS`, `WITHDRAW_MIN_REFERRALS` |
| Операционные | `MAINTENANCE_MODE`, `MAINTENANCE_TEXT`, `BROADCAST_RATE_PER_SEC`, `THROTTLE_SECONDS` |
| PiarFlow | `PIARFLOW_ENABLED`, `PIARFLOW_API_KEY`, `PIARFLOW_API_URL`, `PIARFLOW_MAX_SPONSORS`, `PIARFLOW_UNSUB_PENALTY` |
| Fragment | `FRAGMENT_WALLET_MNEMONIC`, `FRAGMENT_COOKIES`, `FRAGMENT_TONAPI_KEY`, `FRAGMENT_WALLET_VERSION` |
| Антитвинк / ОП | `DEVICE_CHECK_FOR_OP`, `TWINK_BLOCK_OP` |
| Логи | `LOG_LEVEL`, `LOG_JSON` |

Все параметры экономики, лимиты вывода, каналы manual-ОП, контакт поддержки и режим обслуживания
можно переопределить в **Админка → ⚙️ Настройки**. Переопределение хранится в БД, помечается ✏️
и сбрасывается к значению из `.env` одной кнопкой.

## Антитвинк: проверка устройства через Mini App

Мультиаккаунты («твинки») — главный способ накрутки рефералки. Бот поднимает встроенный
веб-сервер (aiohttp) на порту `SERVER_PORT`, доступный по HTTPS-адресу контейнера
(`WEB_PUBLIC_URL`), и показывает пользователю кнопку **«🛡 Подтвердить устройство»** —
это Telegram Mini App. Страница за секунду собирает отпечаток устройства (user agent,
экран, GPU/canvas, таймзона, языки, шрифты, платформа и версия Telegram), хэширует его и
отправляет на `/api/device` вместе с `initData`. Сервер проверяет подпись `initData`
(HMAC на токене бота — подделать чужой `user_id` невозможно), добавляет IP и связывает
отпечаток с аккаунтом.

Политика (все флаги — в **Настройки → Антитвинк**, без перезапуска):

- Пока устройство не подтверждено, реферальный бонус за пользователя **не начисляется**
  (ежедневка, задания, промокоды работают); при `DEVICE_CHECK_FOR_WITHDRAW` недоступен и вывод.
- Второй аккаунт с тем же отпечатком помечается **твинком** (`twink_of` = первый аккаунт):
  бонус рефереру не платится, его заработок не даёт долю рефереру, в карточке заявки на
  вывод админ видит «👯 Твинк! То же устройство у: …». `TWINK_BLOCK_WITHDRAW` запрещает вывод.
- `TWINK_REQUIRE_IP_MATCH` смягчает правило для популярных моделей устройств: твинк —
  только если совпали и отпечаток, и IP за `TWINK_IP_WINDOW_DAYS` дней.
- Админ может отметить пользователя **🤝 доверенным** (семья с одним телефоном): флаг
  снимается, отложенный бонус выплачивается при следующей активности.
- Раздел **🕵️ Антифрод → 👯 Твинки** показывает кластеры «одно устройство — несколько аккаунтов».

Честное ограничение: отпечаток снимает браузер, и технически подкованный человек может
подменить его на каждом аккаунте. Это отсекает массовый сценарий (несколько аккаунтов в одном
приложении Telegram, фермы на одном устройстве), а не целевую атаку — поэтому IP и история
проверок хранятся и видны админу. Эндпоинты: `GET /` (лендинг), `GET /health`,
`GET /verify` (Mini App), `POST /api/device` (лимит 20 запросов/мин с IP).

## Вывод Stars

Пользователь выбирает **готовый подарок** из каталога Telegram (`getAvailableGifts`), а не
произвольную сумму. Стоимость подарка (`star_count`) резервируется на балансе бота-экономики:

1. Пользователь создаёт заявку на подарок — сумма **резервируется** (холд), админы получают карточку.
2. Админ нажимает **Согласовать** → пользователь получает уведомление.
3. Админ жмёт **Отправить подарок** — бот вызывает `sendGift` (Stars списываются с баланса бота)
   и сразу помечает заявку как `sent`. Либо отмечает **Уже отправил вручную**, если подарок ушёл иначе.
4. **Отклонить** (с причиной) или отмена самим пользователем — холд возвращается на баланс.

На балансе бота должно быть достаточно Stars для `sendGift`. Не подтверждайте отправку, пока подарок
реально не ушёл.

## Платежи и возвраты

Бусты продаются как цифровые товары за XTR (`sendInvoice`, `currency="XTR"`). Каждый платёж
сохраняется в `payments`. Админ может вернуть покупку из карточки платежа: бот вызывает
`refundStarPayment`, списывает начисленные Stars пака (баланс может уйти в минус — это видно в
карточке) или мгновенно отключает множитель, пользователь получает уведомление.
Команды `/paysupport` и `/terms` отвечают требованиям Telegram к ботам, принимающим Stars.

## ОП (PiarFlow)

Провайдер без ключа не блокирует пользователей (skip), ошибка API — fail-open. Порядок фиксирован:
PiarFlow. Админ может выключить любого
провайдера в рантайме (таблица `provider_states`) и управлять списком своих каналов.

Адаптеры реализованы по официальной документации сервисов, контракты закреплены тестами
(`tests/test_op_adapters.py`) на примерах ответов из документации:

| Провайдер | Документация | Запрос | Проверка «Я подписался» |
| --- | --- | --- | --- |
| Flyer | [api.flyerhubs.com](https://api.flyerhubs.com/) | ключ `sub`: `POST /check` (`skip`), Flyer сам присылает сообщение со спонсорами; ключ `tasks`: `POST /get_tasks` → `result[].links[]`, статусы `incomplete/abort` = не выполнено | повтор запроса; тип ключа определяется через `POST /get_me` |
| SubGram | subgram.ru | `POST /get-sponsors`, заголовок `Auth` | `POST /get-user-subscriptions` |
| BotoHub | [botohub.me/integration](https://botohub.me/integration) | `POST /get-tasks-extended`, заголовок `Auth`, тело `{chat_id, max_op}` → `tasks[].{url, completed}`, `completed`, `skip` | повтор запроса (спонсоры закреплены на 3 мин) |
| PiarFlow | [piarflow.com/api-docs](https://piarflow.com/api-docs) | `POST /sponsors`, `Authorization: Bearer` → `sponsors[].{link, status}` (`not_counted` = выполнено) | `POST /sponsors/check` с показанными `links` |
| TGrass | [tgrass.space/integration](https://tgrass.space/integration) | `POST /offers`, заголовок `Auth`, тело `{tg_user_id, is_premium, lang, tg_login}` → `status ok/not_ok/no_offers`, `offers[].subscribed` | повтор запроса; плюс локальный список `TGRASS_CHANNELS` |
| Trafsly | [trafsly.com/api-docs](https://trafsly.com/api-docs) | `POST /api/v1/get-sponsors`, заголовок `Auth: at_…` → `status ok/warning`, `sponsors[].{ads_id, link, title}` | `POST /api/v1/confirm-subscription` по каждому выданному `ads_id`; `Sponsor was not shown` / `Order not found` → повторный запрос списка |
| manual | — | `getChatMember` по `MANUAL_OP_CHANNELS` (редактируется из панели) | повтор проверки |

Старые плейсхолдеры URL из прежнего `.env.example` (`api.flyerservice.io`, `botohub.me/api/v1`,
`api.tgrass.online/v1`) автоматически заменяются на документированные хосты.

### Свои каналы: публичные, приватные и платные

Запись канала — `@username`, `@username|Название` или
`-1001234567890|https://t.me/+ссылка|Название`. Первое поле — что бот **проверяет** через
`getChatMember` (бот должен быть администратором канала), ссылка — куда ведёт **кнопка**,
название — подпись кнопки. Для приватных и платных каналов ссылка обязательна: `t.me/c/<id>`
открывается только у участников. Платный канал подключается платной пригласительной ссылкой
(цена в Stars) — оплативший подписку числится `member`, истёкшая подписка → `left`, и ОП снова
покажет кнопку.

В панели (**📢 Каналы ОП → Добавить**) достаточно **переслать любой пост из канала**: бот
определит ID и название, для приватного канала попросит ссылку, а по команде `auto` /
`auto 50` сам создаст бесплатную или платную (50 ⭐/мес) пригласительную ссылку
(`createChatSubscriptionInviteLink`, нужно право «Приглашать пользователей»). Тот же формат
работает в заданиях типа «Подписка на канал».

### Как добавить OP-провайдера

1. Создайте `app/op/myprovider.py` с классом-адаптером:
   - `name: str`
   - `async def check(user: OpContext) -> OpResult`
   - `async def verify(user: OpContext) -> OpResult` (кнопка «Я подписался»)
2. Если нет ключа — `OpResult.skip(...)`. Если API упал — `OpResult.fail_open_result(...)`.
   Если есть невыполненные спонсоры — `OpResult.blocked(name, sponsors)`.
3. Зарегистрируйте адаптер в `default_adapters()` и имя в `CASCADE` / `PROVIDER_TITLES` (`app/op/gate.py`)
   и `PROVIDER_NAMES` (`app/db/seed.py`).
4. Добавьте `*_ENABLED` и ключи в `app/config.py` и `.env.example`; учтите их в `provider_configured()`.

Эффективные настройки (с учётом переопределений из БД) доступны адаптеру через `OpContext.settings`.
Добавьте контрактный тест в `tests/test_op_adapters.py` с примером ответа из документации провайдера —
`FakeHttp` подменяет `post_json` в модуле адаптера.

## Миграции

Схема управляется Alembic (`app/migrations`). При старте бот сам приводит БД к актуальной ревизии:

- пустая БД → создаётся с нуля;
- БД от версии 0.1 (`create_all`, без `alembic_version`) → штампуется `0001_baseline` и обновляется,
  баланс бэкфиллится из леджера;
- иначе — обычный `upgrade head`.

Ручная работа с миграциями из корня проекта:

```bash
alembic current
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```

Новые миграции держите аддитивными (ADD COLUMN / CREATE TABLE), чтобы они применялись на SQLite без пересборки таблиц.

## Тесты и качество

```bash
pytest          # 124 теста
ruff check .    # линт
ruff format .   # форматирование
```

Покрыты: атомарный леджер и сверка, холд/возврат/легаси-путь выводов, идемпотентность платежей и
возвраты, ежедневка и серии, задания (включая проверку подписки), рефералы (первый старт,
уровни, доля), промокоды, настройки в рантайме, роли админов, аудит, фоновая рассылка (блокировки,
`RetryAfter`, отмена), статистика/лидерборд/экспорт, миграции (fresh == `create_all`, легаси-штамп),
контракты ОП-провайдеров (Flyer sub/tasks, BotoHub, TGrass, PiarFlow, Trafsly — на примерах из
документации, включая ошибки и fail-open), middleware и **end-to-end сценарии через реальный
диспетчер** с фейковой Telegram-сессией
(`tests/fake_telegram.py`): старт и ОП-гейт, рефералы, ежедневка, вывод с уведомлениями, админ-панель,
настройки и режим обслуживания, платежи с возвратом, промокоды, задания, рассылка, экспорт, управление админами.

## Структура

```
main.py                  # RubyHost / Pterodactyl: APP PY FILE=main.py
alembic.ini              # CLI Alembic (бот применяет миграции сам)
Dockerfile, docker-compose.yml
app/
  __main__.py            # жизненный цикл: миграции → сид → polling → graceful shutdown
  config.py              # Settings + белый список рантайм-настроек
  bot/
    factory.py           # Bot, Dispatcher, порядок middleware
    handlers/            # пользовательские роутеры (start, commands, cabinet, earn, withdraw, promo, payments, system)
    admin/               # админ-панель: router, texts, keyboards, states + разделы
    middlewares/         # context, throttle, db(+events), runtime(settings/access/maintenance), user, op_gate
    notify.py            # доменные события → уведомления Telegram
    errors.py            # глобальный обработчик ошибок
  services/              # ledger, users, referrals, daily, tasks, boosts, payments, economy,
                         # withdrawals, promo, access, audit, app_settings, broadcasts, stats,
                         # leaderboard, export, antifraud, events
  op/                    # OpGate + адаптеры, общий aiohttp-клиент
  db/                    # models, session, seed, migrate
  migrations/            # Alembic env + versions
tests/                   # pytest (сервисы, middleware, миграции, e2e через диспетчер)
docs/superpowers/specs/  # дизайн-спека v1.0
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
