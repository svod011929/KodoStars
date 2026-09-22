"""Admin settings hubs must cover every runtime-overridable key exactly once."""

from app.config import (
    RUNTIME_OVERRIDABLE,
    SETTINGS_GROUP_LABELS,
    SETTINGS_GROUPS,
    setting_group,
)


def test_settings_groups_partition_runtime_keys() -> None:
    grouped: list[str] = []
    for group_id, keys in SETTINGS_GROUPS.items():
        assert group_id in SETTINGS_GROUP_LABELS
        assert keys, f"empty group {group_id}"
        grouped.extend(keys)

    assert len(grouped) == len(set(grouped)), "duplicate key across settings groups"
    assert set(grouped) == set(RUNTIME_OVERRIDABLE), (
        f"missing={set(RUNTIME_OVERRIDABLE) - set(grouped)} "
        f"extra={set(grouped) - set(RUNTIME_OVERRIDABLE)}"
    )


def test_setting_group_lookup() -> None:
    assert setting_group("withdraw_min") == "withdraw"
    assert setting_group("botohub_views_token") == "traffic"
    assert setting_group("not_a_key") is None
