# Ambassador System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (or subagent-driven-development) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users apply with channel/chat/bot slots; admins approve with custom L1/L2 referral terms and daily promo templates; ambassadors claim one promo/day (UTC) with optional auto-post to channel/chat.

**Architecture:** `AmbassadorSlot` rows own platform + terms. `effective_referral_terms(referrer_id)` takes max of each field across approved slots (else global Settings). Daily promos are normal `PromoCode` rows with `ambassador_slot_id` + day uniqueness. Auto-post is a two-step admin flag gated on bot admin rights.

**Tech Stack:** aiogram 3, SQLAlchemy async, Alembic, pytest, existing promo/referral/admin patterns.

## Global Constraints

- Migration id: `0008_ambassador_slots` (revises `0007_piarflow_issued_subs`)
- Branch: `kododrive/ambassador-system-575a`
- Spec: `docs/superpowers/specs/2026-09-22-ambassador-system-design.md`
- Russian UI copy; `{bot}` / `BOT` brand glyphs where branding appears
- No inline imports; exhaustive switches with `never` default
- TDD: failing test → implement → pass → commit per task
- One UTC calendar day = one promo per approved slot

## File map

| File | Responsibility |
|---|---|
| `app/db/models.py` | `AmbassadorKind`, `AmbassadorStatus`, `AmbassadorSlot`; `PromoCode.ambassador_slot_id` |
| `app/migrations/versions/0008_ambassador_slots.py` | Schema |
| `app/services/ambassadors.py` | Apply/approve/reject/revoke, terms, daily promo, auto-post helpers |
| `app/services/referrals.py` | Use effective terms for bonus/% |
| `app/services/promo.py` | Allow `ambassador_slot_id` on create |
| `app/bot/handlers/ambassador.py` | User FSM + screens |
| `app/bot/admin/ambassadors.py` | Admin queue + approve FSM |
| `app/bot/keyboards.py`, `texts.py`, FSM states | User chrome |
| `app/bot/admin/keyboards.py`, `texts.py`, `home.py`, `router.py`, `states.py` | Admin chrome |
| `tests/test_ambassadors.py` | Core coverage |

---

### Task 1: Models + migration + terms resolver

**Files:**
- Modify: `app/db/models.py`
- Create: `app/migrations/versions/0008_ambassador_slots.py`
- Create: `app/services/ambassadors.py` (terms + normalize first)
- Test: `tests/test_ambassadors.py`

**Interfaces:**
- Produces:
  - `class ReferralTerms: l1_bonus, l1_percent, l2_bonus, l2_percent` (dataclass)
  - `def normalize_invite_link(raw: str) -> str`
  - `async def effective_referral_terms(session, referrer_id, settings) -> ReferralTerms`
  - enums `AmbassadorKind`, `AmbassadorStatus`
  - model `AmbassadorSlot`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_ambassadors.py
import pytest
from app.config import Settings
from app.db.models import AmbassadorKind, AmbassadorStatus, AmbassadorSlot, User
from app.services import ambassadors as amb


@pytest.mark.asyncio
async def test_effective_terms_defaults_to_settings(session, settings):
    user = User(id=10, first_name="A")
    session.add(user)
    await session.commit()
    terms = await amb.effective_referral_terms(session, 10, settings)
    assert terms.l1_bonus == settings.referral_l1_bonus
    assert terms.l1_percent == settings.referral_l1_percent


@pytest.mark.asyncio
async def test_effective_terms_takes_max_across_approved_slots(session, settings):
    session.add(User(id=10, first_name="A"))
    session.add_all([
        AmbassadorSlot(
            user_id=10, kind=AmbassadorKind.CHANNEL, title="C1",
            invite_link="https://t.me/c1", status=AmbassadorStatus.APPROVED,
            l1_bonus=20, l1_percent=10, l2_bonus=1, l2_percent=2,
            promo_reward=5, promo_max_uses=10,
        ),
        AmbassadorSlot(
            user_id=10, kind=AmbassadorKind.CHAT, title="C2",
            invite_link="https://t.me/c2", status=AmbassadorStatus.APPROVED,
            l1_bonus=15, l1_percent=25, l2_bonus=5, l2_percent=1,
            promo_reward=5, promo_max_uses=10,
        ),
        AmbassadorSlot(
            user_id=10, kind=AmbassadorKind.BOT, title="B",
            invite_link="https://t.me/b", status=AmbassadorStatus.REVOKED,
            l1_bonus=100, l1_percent=90, l2_bonus=50, l2_percent=40,
            promo_reward=5, promo_max_uses=10,
        ),
    ])
    await session.commit()
    terms = await amb.effective_referral_terms(session, 10, settings)
    assert (terms.l1_bonus, terms.l1_percent, terms.l2_bonus, terms.l2_percent) == (20, 25, 5, 2)


def test_normalize_invite_link():
    assert amb.normalize_invite_link(" https://T.ME/Foo/ ") == "https://t.me/foo"
```

Fix typo in real test file: use `invite_link=` not `invite of_link`.

- [ ] **Step 2: Run tests — expect FAIL** (`ambassadors` / models missing)

Run: `python3 -m pytest tests/test_ambassadors.py -q --tb=line`

- [ ] **Step 3: Implement models**

Add to `app/db/models.py`:

```python
class AmbassadorKind(StrEnum):
    CHANNEL = "channel"
    CHAT = "chat"
    BOT = "bot"

class AmbassadorStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVOKED = "revoked"

AMBASSADOR_KIND_LABELS = {
    AmbassadorKind.CHANNEL.value: "Канал",
    AmbassadorKind.CHAT.value: "Чат",
    AmbassadorKind.BOT.value: "Бот",
}
AMBASSADOR_STATUS_LABELS = {
    AmbassadorStatus.PENDING.value: "На проверке",
    AmbassadorStatus.APPROVED.value: "Одобрен",
    AmbassadorStatus.REJECTED.value: "Отклонён",
    AmbassadorStatus.REVOKED.value: "Отозван",
}

class AmbassadorSlot(Base):
    __tablename__ = "ambassador_slots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(128))
    invite_link: Mapped[str] = mapped_column(String(512))
    chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=AmbassadorStatus.PENDING.value, index=True)
    l1_bonus: Mapped[int | None] = mapped_column(Integer, nullable=True)
    l1_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    l2_bonus: Mapped[int | None] = mapped_column(Integer, nullable=True)
    l2_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    promo_reward: Mapped[int | None] = mapped_column(Integer, nullable=True)
    promo_max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    promo_auto_post: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

Add `ambassador_slot_id: Mapped[int | None]` FK on `PromoCode` (nullable).

- [ ] **Step 4: Migration `0008_ambassador_slots.py`**

Create table + indexes `(user_id)`, `(status)`, `(user_id, status)`; add `promo_codes.ambassador_slot_id` FK nullable; add `promo_day_key` String(10) nullable on promo_codes for uniqueness `uq_ambassador_promo_day (ambassador_slot_id, promo_day_key)` where both set (SQLite: plain UniqueConstraint is fine if day_key null for non-amb promos — use empty string only for amb codes, or store day always for amb).

Practical approach for SQLite: column `promo_day_key` nullable; UniqueConstraint(`ambassador_slot_id`, `promo_day_key`); non-amb promos leave both null (SQLite allows multiple NULLs in unique).

- [ ] **Step 5: Implement `app/services/ambassadors.py` terms helpers**

```python
@dataclass(frozen=True)
class ReferralTerms:
    l1_bonus: int
    l1_percent: int
    l2_bonus: int
    l2_percent: int

    def bonus(self, level: int) -> int: ...
    def percent(self, level: int) -> int: ...

def normalize_invite_link(raw: str) -> str:
    return raw.strip().rstrip("/").lower()

async def effective_referral_terms(session, referrer_id: int, settings: Settings) -> ReferralTerms:
    # select approved slots for user; max each field; fill from settings if no slots
```

- [ ] **Step 6: Tests pass** → commit `feat: ambassador models and effective referral terms`

---

### Task 2: Slot lifecycle + daily promo service

**Files:**
- Modify: `app/services/ambassadors.py`, `app/services/promo.py`
- Test: `tests/test_ambassadors.py`

**Interfaces:**
- Produces:
  - `async def submit_application(session, *, user, kind, title, invite_link) -> AmbassadorSlot`
  - `async def approve_slot(session, *, slot_id, admin_id, l1_bonus, l1_percent, l2_bonus, l2_percent, promo_reward, promo_max_uses) -> AmbassadorSlot`
  - `async def reject_slot(session, *, slot_id, admin_id, reason) -> AmbassadorSlot`
  - `async def revoke_slot(session, *, slot_id, admin_id) -> AmbassadorSlot`
  - `async def claim_daily_promo(session, *, slot_id, user_id) -> PromoCode`
  - `async def todays_promo(session, slot_id) -> PromoCode | None`
  - `def utc_day_key(now=None) -> str`  # `YYYY-MM-DD`

- [ ] **Step 1: Failing tests** for submit duplicate, approve, claim once/day, revoke removes terms

- [ ] **Step 2: Implement lifecycle** — pending→approved/rejected; approved→revoked; validate kind enum; duplicate pending/approved same normalized link → `ValidationError`

- [ ] **Step 3: `claim_daily_promo`** — require approved + owner; if todays exists return it; else `promo.create_promo` with `ambassador_slot_id`, `promo_day_key`, expires end of UTC day; code `AMB` + secrets.token_hex(4).upper()

Extend `create_promo(..., ambassador_slot_id=None, promo_day_key=None)`.

- [ ] **Step 4: Pass + commit** `feat: ambassador apply/approve and daily promo claim`

---

### Task 3: Wire referrals to effective terms

**Files:**
- Modify: `app/services/referrals.py` (`activate_if_ready`, `share_earning`)
- Test: `tests/test_ambassadors.py` (+ existing referral tests still pass)

- [ ] Replace `settings.referral_bonus(level)` / `settings.referral_percent(level)` with:

```python
terms = await amb.effective_referral_terms(session, referrer.id, settings)
bonus = terms.bonus(edge.level)
percent = terms.percent(edge.level)
```

Cache terms per referrer_id inside the loop to avoid N queries (dict memo).

- [ ] Test: approved slot with l1_bonus=50 → activation credits 50 (before multipliers) for L1.

- [ ] Commit `feat: use ambassador terms in referral payouts`

---

### Task 4: User UI

**Files:**
- Create: `app/bot/handlers/ambassador.py`
- Modify: `app/bot/handlers/states.py`, `keyboards.py`, `texts.py`, `handlers/__init__.py`

**Callbacks:** `menu:amb`, `amb:new`, `amb:kind:*`, `amb:slot:{id}`, `amb:claim:{id}`, `amb:post:{id}`

FSM `UserFSM`: `amb_link`, `amb_title` (kind stored in state data).

- [ ] Menu button «Амбассадор»
- [ ] List slots / apply / card / claim
- [ ] Register router
- [ ] Smoke test via harness optional; unit texts/keyboards ok
- [ ] Commit `feat: user ambassador menu and apply flow`

---

### Task 5: Admin UI

**Files:**
- Create: `app/bot/admin/ambassadors.py`
- Modify: admin `keyboards.py`, `texts.py`, `home.py`/`keyboards.home`, `router.py`, `states.py`

**Callbacks:** `admin:amb`, `admin:amb:pending`, `admin:amb:list`, `admin:amb:{id}`, approve FSM (6 numeric fields), reject reason, revoke, set chat_id, check rights, toggle auto_post

Approve FSM states: `amb_l1_bonus`, `amb_l1_percent`, `amb_l2_bonus`, `amb_l2_percent`, `amb_promo_reward`, `amb_promo_max_uses` (or one multi-step like promo create).

Notify admins on new application via existing `Notifier` / `events` if cheap; else skip and show pending badge count on hub button `Амбассадоры (N)`.

- [ ] Commit `feat: admin ambassador approval hub`

---

### Task 6: Auto-post + bot admin check

**Files:**
- Modify: `app/services/ambassadors.py`, admin + user handlers

**Interfaces:**
- `async def bot_is_chat_admin(bot, chat_id) -> bool`
- `async def enable_auto_post(session, bot, slot_id) -> AmbassadorSlot`  # raises if not admin / wrong kind / no chat_id
- `async def publish_promo(bot, slot, promo) -> None`

- [ ] Tests with FakeSession / mock bot methods
- [ ] On claim: if `promo_auto_post` try publish; on failure clear flag
- [ ] Commit `feat: ambassador promo auto-post`

---

### Task 7: Polish + full suite + PR

- [ ] README short section under features
- [ ] `python3 -m pytest tests/ -q` — all green
- [ ] Push + `ManagePullRequest` create/update PR to `main`
- [ ] Commit `docs: document ambassador program`

---

## Spec coverage checklist

| Spec item | Task |
|---|---|
| AmbassadorSlot + statuses | 1 |
| Max terms across approved | 1–3 |
| Apply / approve / reject / revoke | 2, 5 |
| Daily promo hybrid | 2, 4 |
| Two-step auto-post | 6 |
| Multi slots per user | 1–2 |
| User + admin UI | 4–5 |
| Migration 0008 | 1 |
| Tests | 1–6 |
| Out of scope analytics/ownership proof | — skipped |

## Placeholder scan

None intentional. `promo_day_key` chosen over partial SQL index for SQLite compatibility.
