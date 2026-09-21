# KodoStars — PiarFlow-only + Fragment payouts

Дата: 2026-09-21. Автономный cloud-agent: решения зафиксированы по запросу без промежуточных вопросов.

## Цель

Снизить жалобы PiarFlow на качество трафика (твинки) и упростить монетизацию до одного провайдера, с вебхуком отписок и выплатой Stars через Fragment.

## Решения

### 1. Только PiarFlow
- Каскад ОП: единственный адаптер `piarflow`.
- Удалены Flyer, SubGram, BotoHub, TGrass, Trafsly, manual и UI «Каналы ОП».
- Env/админка: остаются только `PIARFLOW_*`.

### 2. Антитвинк до ОП
- Перед любым вызовом `/sponsors` пользователь обязан пройти Mini App проверку устройства (`DEVICE_CHECK_FOR_OP`, по умолчанию true).
- Твинки (`twink_of` и не `is_trusted`) не получают задания ОП (`TWINK_BLOCK_OP`, по умолчанию true).
- Непроверенные / твинки видят только кнопку подтверждения устройства / сообщение о блокировке — без HTTP к PiarFlow.

### 3. Вебхук отписок
- HTTPS endpoint: `POST {WEB_PUBLIC_URL}/api/piarflow/webhook`.
- `test=true` → `{"ok": true}` без побочных эффектов.
- `status=unsubscribed` → сброс `last_op_ok_at`, штраф `PIARFLOW_UNSUB_PENALTY` Stars (списание с баланса, не ниже 0), уведомление пользователю.
- Идемпотентность: таблица `piarflow_unsubs` с уникальным ключом `(tg_user_id, offer_link)`.

### 4. Выплаты через Fragment
- Env (только сервер, не в git): `FRAGMENT_WALLET_MNEMONIC`, `FRAGMENT_COOKIES`.
- Опционально `FRAGMENT_TONAPI_KEY` (tonconsole) — без него используется публичный Toncenter.
- Вывод: сумма (каталог подарков как пресеты star_count) → заявка → админ «Отправить через Fragment».
- Требуется `@username` у получателя (Fragment принимает username).
- Библиотека: `fragment-api-py` (cookies + mnemonic, подпись локально).

### 5. Секреты
- Реальные mnemonic/cookies **не коммитятся**. В `.env.example` — плейсхолдеры.
- Значения из чата пользователь должен положить только в серверный `.env` и при утечке в чат — сменить кошелёк/сессию.

## Вне скоупа
- CryptoBot / другие OP-провайдеры.
- Полный редизайн UX.
