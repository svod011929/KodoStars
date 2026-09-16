import pytest

from app.config import RUNTIME_OVERRIDABLE
from app.db.models import AdminRole
from app.services import audit
from app.services.access import AccessRegistry
from app.services.app_settings import RuntimeSettingsStore, format_value, parse_value
from app.services.errors import AccessDenied, NotFound, ValidationError


@pytest.mark.asyncio
async def test_access_registry_roles(session) -> None:
    access = AccessRegistry(frozenset({1}))
    await access.load(session)
    assert access.is_owner(1) and access.is_admin(1)
    assert access.role(1) == AdminRole.OWNER
    assert not access.is_admin(2)

    await access.add_admin(session, user_id=2, actor_id=1)
    assert access.is_admin(2) and not access.is_owner(2)
    assert access.role(2) == AdminRole.ADMIN
    assert access.all_admin_ids() == frozenset({1, 2})

    with pytest.raises(AccessDenied):
        await access.add_admin(session, user_id=3, actor_id=2)
    with pytest.raises(ValidationError):
        await access.add_admin(session, user_id=2, actor_id=1)
    with pytest.raises(ValidationError):
        await access.add_admin(session, user_id=1, actor_id=1)
    with pytest.raises(ValidationError):
        await access.remove_admin(session, user_id=1, actor_id=1)
    with pytest.raises(NotFound):
        await access.remove_admin(session, user_id=99, actor_id=1)

    await access.remove_admin(session, user_id=2, actor_id=1)
    assert not access.is_admin(2)

    # A fresh registry reloads DB admins.
    await access.add_admin(session, user_id=5, actor_id=1)
    other = AccessRegistry(frozenset({1}))
    await other.load(session)
    assert other.is_admin(5)


@pytest.mark.asyncio
async def test_audit_log(session) -> None:
    await audit.log_action(
        session, admin_id=1, action="user.ban", target_type="user", target_id=7, reason="x"
    )
    await audit.log_action(
        session, admin_id=1, action="settings.set", target_type="setting", target_id="withdraw_min", value=10
    )
    rows = await audit.recent(session, limit=5)
    assert [r.action for r in rows] == ["settings.set", "user.ban"]
    assert rows[1].target_id == "7"
    assert rows[1].detail == {"reason": "x"}
    assert await audit.count(session) == 2
    assert audit.label("user.ban") == "Бан"
    assert audit.label("custom.thing") == "custom.thing"


def test_parse_and_format_values() -> None:
    assert parse_value("withdraw_min", " 25 ") == 25
    assert parse_value("maintenance_mode", "вкл") is True
    assert parse_value("maintenance_mode", "off") is False
    assert parse_value("support_contact", "@kodo") == "@kodo"
    with pytest.raises(ValidationError):
        parse_value("withdraw_min", "abc")
    with pytest.raises(ValidationError):
        parse_value("maintenance_mode", "maybe")
    with pytest.raises(ValidationError):
        parse_value("bot_token", "x")
    assert format_value(True) == "вкл"
    assert format_value("") == "—"
    assert format_value(7) == "7"


@pytest.mark.asyncio
async def test_runtime_settings_store(session, settings) -> None:
    store = RuntimeSettingsStore(settings)
    effective = await store.effective(session)
    assert effective.withdraw_min == settings.withdraw_min
    assert effective is settings  # no overrides → same object

    await store.set(session, key="withdraw_min", raw="10", admin_id=1)
    await store.set(session, key="maintenance_mode", raw="on", admin_id=1)
    effective = await store.effective(session)
    assert effective.withdraw_min == 10
    assert effective.maintenance_mode is True
    assert settings.withdraw_min == 50  # base untouched
    assert set((await store.overrides(session)).keys()) == {"withdraw_min", "maintenance_mode"}

    # Validation goes through the Settings model.
    with pytest.raises(ValidationError):
        await store.set(session, key="referral_l1_percent", raw="150", admin_id=1)
    with pytest.raises(ValidationError):
        await store.set(session, key="withdraw_max", raw="5", admin_id=1)  # < withdraw_min
    with pytest.raises(ValidationError):
        await store.set(session, key="database_url", raw="x", admin_id=1)

    await store.reset(session, key="withdraw_min")
    assert (await store.effective(session)).withdraw_min == 50

    # Persisted: a new store instance sees the DB overrides.
    fresh = RuntimeSettingsStore(settings)
    assert (await fresh.effective(session)).maintenance_mode is True
    assert fresh.default_value("maintenance_mode") is False


def test_every_overridable_key_exists_on_settings(settings) -> None:
    for key, kind in RUNTIME_OVERRIDABLE.items():
        assert hasattr(settings, key), key
        assert isinstance(getattr(settings, key), kind), key
