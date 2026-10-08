"""Weekly referral contest: week math, who counts on the board, settlement."""

from datetime import UTC, datetime, timedelta
from itertools import count

import pytest
from sqlalchemy import func, select

from app.bot import texts
from app.config import Settings, parse_prizes
from app.db.models import Contest, ContestStatus, ContestWinner, ReferralEdge, User
from app.services import contests, events, ledger

WEEK = contests.week_of(datetime(2026, 10, 7, 15, 30, tzinfo=UTC))  # Wednesday, 2026-W41
_friend_ids = count(10_000)


def _at(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 10, day, hour, tzinfo=UTC)


async def _user(session, user_id: int, **extra) -> User:
    extra.setdefault("username", f"u{user_id}")
    user = User(id=user_id, first_name=f"U{user_id}", **extra)
    session.add(user)
    await session.flush()
    return user


async def _friend(session, referrer_id: int, activated_at: datetime | None, **extra) -> User:
    friend = await _user(session, next(_friend_ids), referral_activated=activated_at is not None, **extra)
    session.add(
        ReferralEdge(referrer_id=referrer_id, referee_id=friend.id, level=1, credited_at=activated_at)
    )
    await session.flush()
    return friend


async def _open(session, week: contests.Week = WEEK) -> Contest:
    contest = Contest(week_key=week.key, starts_at=week.starts_at, ends_at=week.ends_at)
    session.add(contest)
    await session.flush()
    return contest


def test_weeks_run_monday_to_monday_utc() -> None:
    assert WEEK.key == "2026-W41"
    assert (WEEK.starts_at, WEEK.ends_at) == (
        datetime(2026, 10, 5, tzinfo=UTC),
        datetime(2026, 10, 12, tzinfo=UTC),
    )
    assert contests.week_of(datetime(2026, 10, 11, 23, 59, 59, tzinfo=UTC)) == WEEK
    assert contests.week_of(datetime(2026, 10, 12, tzinfo=UTC)).key == "2026-W42"
    assert contests.week_of(datetime(2027, 1, 3, tzinfo=UTC)).key == "2026-W53"
    assert contests.week_of(datetime(2027, 1, 4, tzinfo=UTC)).key == "2027-W01"
    assert contests.week_of(datetime(2026, 10, 7, 15, 30)) == WEEK  # SQLite hands back naive UTC
    assert WEEK.seconds_left(datetime(2026, 10, 11, 23, tzinfo=UTC)) == 3600
    assert WEEK.seconds_left(datetime(2026, 10, 13, tzinfo=UTC)) == 0


def test_prizes_are_a_short_non_increasing_list() -> None:
    assert parse_prizes(" 100, 50 ,25 ") == (100, 50, 25)
    assert parse_prizes("10;10") == (10, 10)
    for bad in ("", "0", "abc", "-5", "10,20", ",".join(["5"] * 11)):
        with pytest.raises(ValueError):
            parse_prizes(bad)
    assert Settings(contest_prizes="70, 30").contest_prizes == "70,30"
    assert Settings(contest_prizes="70, 30").model_copy(
        update={"contest_prizes": "9 ,8"}
    ).contest_prize_list == (
        9,
        8,
    )


@pytest.mark.asyncio
async def test_board_counts_clean_friends_activated_this_week(session) -> None:
    for user_id in range(1, 7):
        await _user(session, user_id)
    for day in (5, 6, 7):
        await _friend(session, 1, _at(day))
    await _friend(session, 1, _at(4))  # previous week
    await _friend(session, 1, None)  # joined, not active yet
    await _friend(session, 1, _at(8), is_banned=True)
    await _friend(session, 1, _at(8), twink_of=999)
    await _friend(session, 1, _at(9), twink_of=999, is_trusted=True)
    # 2 and 3 tie on two friends; 3 got the second one first.
    await _friend(session, 2, _at(6))
    await _friend(session, 2, _at(10))
    await _friend(session, 3, _at(5))
    await _friend(session, 3, _at(9))
    for _ in range(5):
        await _friend(session, 4, _at(6))
        await _friend(session, 5, _at(6))
    (await session.get(User, 4)).is_banned = True
    (await session.get(User, 5)).twink_of = 1
    level_two = await _user(session, next(_friend_ids), referral_activated=True)
    session.add(ReferralEdge(referrer_id=6, referee_id=level_two.id, level=2, credited_at=_at(6)))
    await session.flush()

    board = await contests.standings(session, WEEK)
    assert [(row.place, row.user.id, row.score) for row in board] == [(1, 1, 4), (2, 3, 2), (3, 2, 2)]
    for row in board:
        assert (await contests.place_of(session, WEEK, row.user.id)) == row
    for outsider in (4, 5, 6):
        assert await contests.place_of(session, WEEK, outsider) is None
    assert [row.user.id for row in await contests.standings(session, WEEK, limit=2)] == [1, 3]


@pytest.mark.asyncio
async def test_ties_go_to_whoever_got_there_first(session) -> None:
    for user_id in (1, 2, 3):
        await _user(session, user_id)
    await _friend(session, 1, _at(9))
    await _friend(session, 2, _at(6))
    await _friend(session, 3, _at(6))
    board = await contests.standings(session, WEEK)
    assert [row.user.id for row in board] == [2, 3, 1]
    assert [(await contests.place_of(session, WEEK, user_id)).place for user_id in (1, 2, 3)] == [3, 1, 2]


@pytest.mark.asyncio
async def test_settlement_pays_qualified_places_exactly_once(session, settings) -> None:
    settings.contest_enabled = True
    settings.contest_prizes = "100,50,25"
    settings.contest_min_referrals = 2
    for user_id in (1, 2, 3):
        await _user(session, user_id)
    for day in (5, 6, 7):
        await _friend(session, 1, _at(day))
    for day in (6, 7):
        await _friend(session, 2, _at(day))
    await _friend(session, 3, _at(8))  # third on the board, but below the minimum
    await _open(session)

    assert (
        await contests.settle_due(session, now=WEEK.ends_at - timedelta(seconds=1), settings=settings) == []
    )
    [results] = await contests.settle_due(session, now=WEEK.ends_at, settings=settings)
    contest = results.contest
    assert contest.status == ContestStatus.SETTLED.value and contest.settled_at is not None
    assert (contest.prizes, contest.min_referrals, contest.paid_total) == ([100, 50, 25], 2, 150)
    assert [(w.place, w.user_id, w.score, w.prize) for w, _ in results.winners] == [
        (1, 1, 3, 100),
        (2, 2, 2, 50),
    ]
    assert [await ledger.get_balance(session, user_id) for user_id in (1, 2, 3)] == [100, 50, 0]
    emitted = events.drain(session)
    assert [event.name for event in emitted] == ["contest_prize", "contest_prize", "contest_settled"]
    assert emitted[0].payload == {"user_id": 1, "place": 1, "prize": 100, "score": 3}
    assert emitted[-1].payload["winners"][1] == {
        "place": 2,
        "user_id": 2,
        "name": "@u2",
        "score": 2,
        "prize": 50,
    }

    assert await contests.settle_due(session, now=WEEK.ends_at + timedelta(days=3), settings=settings) == []
    assert await session.scalar(select(func.count()).select_from(ContestWinner)) == 2
    assert await ledger.get_balance(session, 1) == 100

    next_week = contests.week_of(WEEK.ends_at)
    last = await contests.last_results(session, before=next_week)
    assert last is not None and last.contest.week_key == WEEK.key
    assert [(w.place, u.id) for w, u in last.winners] == [(1, 1), (2, 2)]
    assert await contests.last_results(session, before=WEEK) is None


@pytest.mark.asyncio
async def test_switched_off_contest_closes_without_prizes(session, settings) -> None:
    await _user(session, 1)
    for day in (5, 6, 7):
        await _friend(session, 1, _at(day))
    await _open(session)
    settings.contest_enabled = False

    [results] = await contests.settle_due(session, now=WEEK.ends_at, settings=settings)
    assert results.contest.status == ContestStatus.CANCELLED.value and results.winners == ()
    assert await ledger.get_balance(session, 1) == 0
    assert [event.name for event in events.drain(session)] == ["contest_settled"]
    assert await contests.last_results(session, before=contests.week_of(WEEK.ends_at)) is None


@pytest.mark.asyncio
async def test_weeks_open_only_while_enabled_and_are_never_backfilled(session, settings) -> None:
    await _user(session, 1)
    for day in (1, 2, 3):  # 2026-W40, before the contest was switched on
        await _friend(session, 1, _at(day))

    settings.contest_enabled = False
    assert await contests.open_week(session, now=_at(7), settings=settings) is None
    settings.contest_enabled = True
    opened = await contests.open_week(session, now=_at(7), settings=settings)
    assert opened is await contests.open_week(session, now=_at(11, 23), settings=settings)
    assert opened.week_key == WEEK.key and opened.status == ContestStatus.RUNNING.value

    [results] = await contests.settle_due(session, now=WEEK.ends_at + timedelta(minutes=1), settings=settings)
    assert results.contest.week_key == WEEK.key and results.winners == ()
    assert await ledger.get_balance(session, 1) == 0
    assert await session.scalar(select(func.count()).select_from(Contest)) == 1


def test_contest_screen_explains_the_race() -> None:
    leader = contests.Standing(place=1, user=User(id=1, username="leader_one"), score=4)
    second = contests.Standing(place=2, user=User(id=2, first_name="Masha"), score=2)
    me = contests.Standing(place=3, user=User(id=3, username="me"), score=1)
    past = Contest(week_key="2026-W40", starts_at=datetime(2026, 9, 28), ends_at=datetime(2026, 10, 5))
    winner = ContestWinner(place=1, user_id=9, score=7, prize=100)
    last = contests.Results(contest=past, winners=((winner, User(id=9, username="champion")),))

    text = texts.contest(2 * 86400 + 3600, (100, 50), 2, [leader, second, me], me, last)
    assert "Итоги через 2 дн 1 ч" in text
    assert "@le***e — <b>4</b> · 100" in text
    assert "Ma***a — <b>2</b> · 50" in text
    assert "Ты: <b>#3</b> · 1 друг — ещё 1 до призового минимума" in text
    assert "Итоги 28.09–04.10" in text and "@ch***n — 7 · +100" in text

    in_prizes = texts.contest(60, (100, 50), 2, [leader, second], second, None)
    assert "ты в призах" in in_prizes and "Итоги 28.09" not in in_prizes
    chasing = contests.Standing(place=3, user=User(id=3, username="me"), score=2)
    behind = texts.contest(60, (100, 50), 2, [leader, second, chasing], chasing, None)
    assert "ещё 1 до призового места" in behind
    assert "Тебя пока нет в таблице" in texts.contest(60, (100,), 1, [], None, None)
