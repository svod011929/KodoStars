"""OP traffic stats and issued/credited lists for every provider."""

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.admin import keyboards as kb
from app.bot.admin import texts
from app.bot.utils import PAGE_SIZE, parse_id, safe_answer, safe_edit
from app.db.models import User
from app.services import piarflow_quality

router = Router(name="admin.piarflow")


async def _names(session: AsyncSession, user_ids: set[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    result = await session.execute(select(User).where(User.id.in_(user_ids)))
    return {u.id: u.display_name for u in result.scalars().all()}


@router.callback_query(F.data == "admin:pf:stats")
async def pf_stats(call: CallbackQuery, session: AsyncSession) -> None:
    traffic = await piarflow_quality.traffic_by_provider(session)
    await safe_answer(call)
    await safe_edit(call.message, texts.op_traffic(traffic), kb.piarflow_stats())


@router.callback_query(F.data.regexp(r"^admin:pf:issued:(\d+)$"))
async def pf_issued(call: CallbackQuery, session: AsyncSession) -> None:
    page = parse_id(call.data, -1)
    total = await piarflow_quality.count_issued(session)
    rows = await piarflow_quality.list_issued(session, limit=PAGE_SIZE, offset=page * PAGE_SIZE)
    names = await _names(session, {r.user_id for r in rows})
    await safe_answer(call)
    await safe_edit(
        call.message,
        texts.piarflow_issued_list(rows, names, page, total, PAGE_SIZE),
        kb.piarflow_list("issued", page, total),
    )


@router.callback_query(F.data.regexp(r"^admin:pf:credited:(\d+)$"))
async def pf_credited(call: CallbackQuery, session: AsyncSession) -> None:
    page = parse_id(call.data, -1)
    total = await piarflow_quality.count_credited(session)
    rows = await piarflow_quality.list_credited(session, limit=PAGE_SIZE, offset=page * PAGE_SIZE)
    names = await _names(session, {r.user_id for r in rows})
    await safe_answer(call)
    await safe_edit(
        call.message,
        texts.piarflow_credited_list(rows, names, page, total, PAGE_SIZE),
        kb.piarflow_list("credited", page, total),
    )
