"""Weekly referral contest.

Referrers race for the most friends activated during an ISO week (Monday 00:00 UTC
to the next Monday). A week takes part only if the contest was on while it ran: the
scheduler opens a row for the running week and settles it once, after it ends, paying
the configured prizes to the top places.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import ColumnElement, Select, and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.orm.util import AliasedClass

from app.config import Settings
from app.db.models import Contest, ContestStatus, ContestWinner, LedgerKind, ReferralEdge, User
from app.services import events, ledger

STANDINGS_LIMIT = 10


@dataclass(frozen=True, slots=True)
class Week:
    key: str
    starts_at: datetime
    ends_at: datetime

    def seconds_left(self, now: datetime) -> int:
        return max(int((self.ends_at - now).total_seconds()), 0)


@dataclass(frozen=True, slots=True)
class Standing:
    place: int
    user: User
    score: int


@dataclass(frozen=True, slots=True)
class Results:
    contest: Contest
    winners: tuple[tuple[ContestWinner, User], ...]


def _aware(moment: datetime) -> datetime:
    # SQLite returns naive timestamps; everything is stored in UTC.
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def week_of(moment: datetime) -> Week:
    day = _aware(moment).date()
    monday = day - timedelta(days=day.weekday())
    starts_at = datetime.combine(monday, time.min, tzinfo=UTC)
    year, number, _ = monday.isocalendar()
    return Week(key=f"{year}-W{number:02d}", starts_at=starts_at, ends_at=starts_at + timedelta(days=7))


def _week(contest: Contest) -> Week:
    return Week(contest.week_key, _aware(contest.starts_at), _aware(contest.ends_at))


def _clean(user: type[User] | AliasedClass[User]) -> ColumnElement[bool]:
    return and_(user.is_banned.is_(False), or_(user.twink_of.is_(None), user.is_trusted.is_(True)))


def _scores(week: Week) -> Select:
    """Level-1 friends activated during ``week``, per referrer.

    Friends banned or flagged as multi-accounts later drop off the board, and so do
    their points.
    """
    referee = aliased(User)
    return (
        select(
            ReferralEdge.referrer_id.label("user_id"),
            func.count().label("score"),
            func.max(ReferralEdge.credited_at).label("reached_at"),
        )
        .join(referee, referee.id == ReferralEdge.referee_id)
        .where(
            ReferralEdge.level == 1,
            ReferralEdge.credited_at >= week.starts_at,
            ReferralEdge.credited_at < week.ends_at,
            referee.referral_activated.is_(True),
            _clean(referee),
        )
        .group_by(ReferralEdge.referrer_id)
    )


async def standings(session: AsyncSession, week: Week, *, limit: int = STANDINGS_LIMIT) -> list[Standing]:
    """Most friends first; a tie goes to whoever reached that count first."""
    scores = _scores(week).subquery()
    stmt = (
        select(User, scores.c.score)
        .join(scores, scores.c.user_id == User.id)
        .where(_clean(User))
        .order_by(scores.c.score.desc(), scores.c.reached_at.asc(), User.id.asc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [
        Standing(place=place, user=user, score=int(score))
        for place, (user, score) in enumerate(rows, start=1)
    ]


async def place_of(session: AsyncSession, week: Week, user_id: int) -> Standing | None:
    """The user's line on the full board, or ``None`` until a friend of theirs counts."""
    scores = _scores(week).subquery()
    row = (
        await session.execute(
            select(User, scores.c.score, scores.c.reached_at)
            .join(scores, scores.c.user_id == User.id)
            .where(User.id == user_id, _clean(User))
        )
    ).first()
    if row is None:
        return None
    user, score, reached_at = row
    ahead = await session.scalar(
        select(func.count())
        .select_from(scores)
        .join(User, User.id == scores.c.user_id)
        .where(
            _clean(User),
            or_(
                scores.c.score > score,
                and_(scores.c.score == score, scores.c.reached_at < reached_at),
                and_(scores.c.score == score, scores.c.reached_at == reached_at, User.id < user_id),
            ),
        )
    )
    return Standing(place=int(ahead or 0) + 1, user=user, score=int(score))


async def open_week(session: AsyncSession, *, now: datetime, settings: Settings) -> Contest | None:
    """Open the running week while the contest is on. Past weeks are never backfilled."""
    if not settings.contest_enabled:
        return None
    week = week_of(now)
    contest = await session.scalar(select(Contest).where(Contest.week_key == week.key))
    if contest is None:
        contest = Contest(week_key=week.key, starts_at=week.starts_at, ends_at=week.ends_at)
        session.add(contest)
        await session.flush()
    return contest


async def settle_due(session: AsyncSession, *, now: datetime, settings: Settings) -> list[Results]:
    """Settle every finished week that is still running, oldest first."""
    due = await session.scalars(
        select(Contest)
        .where(Contest.status == ContestStatus.RUNNING.value, Contest.ends_at <= now)
        .order_by(Contest.starts_at)
    )
    settled: list[Results] = []
    for contest in due.all():
        results = await _settle(session, contest, now=now, settings=settings)
        if results is not None:
            settled.append(results)
    return settled


async def _settle(
    session: AsyncSession, contest: Contest, *, now: datetime, settings: Settings
) -> Results | None:
    # A contest switched off before the week ended pays nothing.
    status = ContestStatus.SETTLED if settings.contest_enabled else ContestStatus.CANCELLED
    claimed = await session.execute(
        update(Contest)
        .where(Contest.id == contest.id, Contest.status == ContestStatus.RUNNING.value)
        .values(status=status.value, settled_at=now)
    )
    if claimed.rowcount != 1:
        return None
    winners: list[tuple[ContestWinner, User]] = []
    if status is ContestStatus.SETTLED:
        prizes = settings.contest_prize_list
        minimum = settings.contest_min_referrals
        board = await standings(session, _week(contest), limit=len(prizes))
        for standing, prize in zip(board, prizes, strict=False):
            if standing.score < minimum:
                break
            await ledger.credit(
                session,
                user_id=standing.user.id,
                amount=prize,
                kind=LedgerKind.CONTEST_PRIZE,
                reference=f"contest:{contest.week_key}:{standing.place}",
                extra={"week": contest.week_key, "place": standing.place, "score": standing.score},
            )
            winner = ContestWinner(
                contest_id=contest.id,
                place=standing.place,
                user_id=standing.user.id,
                score=standing.score,
                prize=prize,
            )
            session.add(winner)
            winners.append((winner, standing.user))
            events.emit(
                session,
                "contest_prize",
                user_id=standing.user.id,
                place=standing.place,
                prize=prize,
                score=standing.score,
            )
        contest.prizes = list(prizes)
        contest.min_referrals = minimum
        contest.paid_total = sum(winner.prize for winner, _ in winners)
    await session.flush()
    events.emit(
        session,
        "contest_settled",
        week=contest.week_key,
        status=status.value,
        min_referrals=contest.min_referrals,
        paid_total=contest.paid_total,
        winners=[
            {
                "place": winner.place,
                "user_id": user.id,
                "name": user.display_name,
                "score": winner.score,
                "prize": winner.prize,
            }
            for winner, user in winners
        ],
    )
    return Results(contest=contest, winners=tuple(winners))


async def last_results(session: AsyncSession, *, before: Week) -> Results | None:
    """The latest settled week that started before ``before``."""
    contest = await session.scalar(
        select(Contest)
        .where(Contest.status == ContestStatus.SETTLED.value, Contest.starts_at < before.starts_at)
        .order_by(Contest.starts_at.desc())
        .limit(1)
    )
    if contest is None:
        return None
    rows = await session.execute(
        select(ContestWinner, User)
        .join(User, User.id == ContestWinner.user_id)
        .where(ContestWinner.contest_id == contest.id)
        .order_by(ContestWinner.place)
    )
    return Results(contest=contest, winners=tuple((winner, user) for winner, user in rows.all()))
