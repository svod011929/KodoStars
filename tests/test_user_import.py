import pytest
from sqlalchemy import func, select

from app.bot import texts
from app.db.models import LedgerKind, ReferralEdge, User
from app.services import ledger, users
from app.services.user_import import (
    CsvUserRow,
    import_users_from_csv,
    parse_users_csv,
    upsert_imported_users,
)

SAMPLE_CSV = """id,username
21767586,gramads
43827256,biseda1214
46334981,RezaRezaei007
"""


def test_parse_sample_csv() -> None:
    parsed = parse_users_csv(SAMPLE_CSV)
    assert parsed.errors == []
    assert [(row.user_id, row.username) for row in parsed.rows] == [
        (21767586, "gramads"),
        (43827256, "biseda1214"),
        (46334981, "RezaRezaei007"),
    ]


def test_parse_ignores_extra_columns() -> None:
    parsed = parse_users_csv("id,username,note\n10,hello,ignore-me\n")
    assert parsed.errors == []
    assert parsed.rows[0].username == "hello"


def test_parse_utf8_bom_and_empty_lines() -> None:
    raw = (
        "\ufeffid,username\n"
        "\n"
        "21767586,gramads\n"
        "   \n"
        "43827256,biseda1214\n"
    ).encode("utf-8-sig")
    parsed = parse_users_csv(raw)
    assert parsed.errors == []
    assert [row.user_id for row in parsed.rows] == [21767586, 43827256]


def test_parse_invalid_rows_and_header() -> None:
    csv = (
        "id,username\n"
        "not-an-id,foo\n"
        ",emptyid\n"
        "0,zero\n"
        "-5,neg\n"
        "99,ok\n"
    )
    parsed = parse_users_csv(csv)
    assert [row.user_id for row in parsed.rows] == [99]
    messages = [error.format() for error in parsed.errors]
    assert messages[0] == "стр. 2: некорректный id: not-an-id"
    assert "пустой id" in messages[1]
    assert "0" in messages[2]
    assert "-5" in messages[3]


def test_parse_strips_at_and_keeps_id_as_username() -> None:
    parsed = parse_users_csv("ID,USERNAME\n10,@hello\n11,11\n12,\n")
    by_id = {row.user_id: row.username for row in parsed.rows}
    assert by_id[10] == "hello"
    assert by_id[11] == "11"
    assert by_id[12] is None


def test_parse_duplicate_id_keeps_last_username() -> None:
    parsed = parse_users_csv("id,username\n10,first\n10,second\n")
    assert len(parsed.rows) == 1
    assert parsed.rows[0].username == "second"


def test_parse_rejects_wrong_header_and_non_utf8() -> None:
    bad_header = parse_users_csv("user,name\n1,a\n")
    assert bad_header.rows == []
    assert bad_header.errors[0].message == "ожидается заголовок id,username"

    empty = parse_users_csv("\n\n")
    assert empty.rows == []
    assert "пуст" in empty.errors[0].message

    binary = parse_users_csv("id,username\n1,a\n".encode("utf-16"))
    assert binary.rows == []
    assert "UTF-8" in binary.errors[0].message


@pytest.mark.asyncio
async def test_import_creates_users_without_economy(session) -> None:
    result = await import_users_from_csv(session, SAMPLE_CSV)
    assert result.created == 3
    assert result.updated == 0
    assert result.unchanged == 0
    assert result.errors == 0

    gramads = await session.get(User, 21767586)
    assert gramads is not None
    assert gramads.username == "gramads"
    assert gramads.first_name == ""
    assert gramads.language_code == "ru"
    assert gramads.referred_by_id is None
    assert gramads.referral_activated is False
    assert gramads.activity_score == 0
    assert gramads.xp == 0
    assert gramads.level == 1
    assert gramads.is_banned is False
    assert await ledger.get_balance(session, gramads.id) == 0

    edges = await session.execute(select(func.count()).select_from(ReferralEdge))
    assert int(edges.scalar_one()) == 0


@pytest.mark.asyncio
async def test_import_updates_username_only(session) -> None:
    referrer = User(id=1, username="root", first_name="Root")
    existing = User(
        id=21767586,
        username="oldname",
        first_name="Keep",
        is_banned=True,
        ban_reason="fraud",
        referred_by_id=1,
        referral_activated=True,
        activity_score=9,
        xp=40,
        level=3,
    )
    session.add_all([referrer, existing])
    await session.flush()
    await ledger.credit(session, user_id=existing.id, amount=25, kind=LedgerKind.TASK)

    result = await import_users_from_csv(session, SAMPLE_CSV)
    assert result.created == 2
    assert result.updated == 1
    assert result.unchanged == 0

    user = await session.get(User, 21767586)
    assert user is not None
    assert user.username == "gramads"
    assert user.first_name == "Keep"
    assert user.is_banned is True
    assert user.ban_reason == "fraud"
    assert user.referred_by_id == 1
    assert user.referral_activated is True
    assert user.activity_score == 9
    assert user.xp == 40
    assert user.level == 3
    assert await ledger.get_balance(session, user.id) == 25


@pytest.mark.asyncio
async def test_import_skips_empty_username_and_same_name(session) -> None:
    session.add(User(id=10, username="keep"))
    session.add(User(id=11, username="same"))
    await session.flush()

    result = await import_users_from_csv(session, "id,username\n10,\n11,same\n")
    assert result.created == 0
    assert result.updated == 0
    assert result.unchanged == 2

    keep = await session.get(User, 10)
    same = await session.get(User, 11)
    assert keep is not None and keep.username == "keep"
    assert same is not None and same.username == "same"


@pytest.mark.asyncio
async def test_second_import_is_idempotent(session) -> None:
    first = await import_users_from_csv(session, SAMPLE_CSV)
    second = await import_users_from_csv(session, SAMPLE_CSV)
    assert first.created == 3
    assert second.created == 0
    assert second.updated == 0
    assert second.unchanged == 3
    assert second.errors == 0


@pytest.mark.asyncio
async def test_import_does_not_use_signup_path(session, settings) -> None:
    settings.signup_bonus = 50
    csv = "id,username\n500,imported\n"
    imported = await import_users_from_csv(session, csv)
    assert imported.created == 1
    assert await ledger.get_balance(session, 500) == 0

    user, created = await users.upsert_user(
        session,
        telegram_id=500,
        username="imported",
        first_name="Later",
        language_code="ru",
        is_premium=False,
        settings=settings,
    )
    assert created is False
    assert user.username == "imported"
    assert await ledger.get_balance(session, 500) == 0


@pytest.mark.asyncio
async def test_upsert_chunking_and_parse_errors_in_summary(session) -> None:
    rows = [CsvUserRow(line=i, user_id=1000 + i, username=f"u{i}") for i in range(7)]
    result = await upsert_imported_users(session, rows, chunk_size=3)
    assert result.created == 7

    mixed = await import_users_from_csv(
        session,
        "id,username\nbad,x\n1000,u0\n1001,renamed\n",
        chunk_size=2,
    )
    assert mixed.created == 0
    assert mixed.updated == 1
    assert mixed.unchanged == 1
    assert mixed.errors == 1
    assert mixed.error_lines == ["стр. 2: некорректный id: bad"]

    renamed = await session.get(User, 1001)
    assert renamed is not None
    assert renamed.username == "renamed"


def test_admin_import_result_text() -> None:
    text = texts.admin_import_result(1, 2, 3, 4, ["стр. 2: некорректный id: x"])
    assert "Создано: 1" in text
    assert "Обновлено: 2" in text
    assert "Без изменений: 3" in text
    assert "Ошибок: 4" in text
    assert "стр. 2: некорректный id: x" in text
