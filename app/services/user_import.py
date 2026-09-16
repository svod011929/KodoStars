from collections.abc import Sequence
from csv import reader as csv_reader
from dataclasses import dataclass, field
from io import StringIO

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User

CHUNK_SIZE = 500
USERNAME_MAX_LEN = 64
ERROR_PREVIEW_LIMIT = 10


@dataclass(frozen=True, slots=True)
class CsvUserRow:
    line: int
    user_id: int
    username: str | None


@dataclass(frozen=True, slots=True)
class CsvRowError:
    line: int
    message: str

    def format(self) -> str:
        if self.line <= 0:
            return self.message
        return f"стр. {self.line}: {self.message}"


@dataclass
class CsvParseResult:
    rows: list[CsvUserRow] = field(default_factory=list)
    errors: list[CsvRowError] = field(default_factory=list)


@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    errors: int = 0
    error_lines: list[str] = field(default_factory=list)


def parse_users_csv(content: str | bytes) -> CsvParseResult:
    """Parse an admin CSV with header ``id,username``.

    Accepts UTF-8 with an optional BOM. Empty lines are skipped. Invalid
    rows are collected in ``errors`` and do not abort the rest of the file.
    Duplicate ids keep the last username.
    """
    text, decode_error = _decode_csv(content)
    if decode_error is not None:
        return CsvParseResult(errors=[decode_error])

    result = CsvParseResult()
    header: list[str] | None = None
    id_idx = 0
    username_idx = 1
    seen: dict[int, CsvUserRow] = {}

    for line_no, raw in enumerate(csv_reader(StringIO(text)), start=1):
        if not raw or all(not (cell or "").strip() for cell in raw):
            continue
        if header is None:
            header = [_normalize_header(cell) for cell in raw]
            if "id" not in header or "username" not in header:
                result.errors.append(CsvRowError(line_no, "ожидается заголовок id,username"))
                return result
            id_idx = header.index("id")
            username_idx = header.index("username")
            continue

        needed = max(id_idx, username_idx) + 1
        if len(raw) < needed:
            raw = raw + [""] * (needed - len(raw))

        raw_id = raw[id_idx].strip()
        raw_username = raw[username_idx].strip()
        if not raw_id:
            result.errors.append(CsvRowError(line_no, "пустой id"))
            continue
        try:
            user_id = int(raw_id)
        except ValueError:
            result.errors.append(CsvRowError(line_no, f"некорректный id: {raw_id}"))
            continue
        if user_id <= 0:
            result.errors.append(CsvRowError(line_no, f"некорректный id: {raw_id}"))
            continue

        seen[user_id] = CsvUserRow(
            line=line_no,
            user_id=user_id,
            username=_normalize_username(raw_username),
        )

    if header is None:
        result.errors.append(CsvRowError(0, "файл пуст или нет заголовка id,username"))
        return result

    result.rows = list(seen.values())
    return result


async def upsert_imported_users(
    session: AsyncSession,
    rows: Sequence[CsvUserRow],
    *,
    chunk_size: int = CHUNK_SIZE,
) -> ImportResult:
    """Insert missing users and refresh usernames. Does not touch economy.

    Each chunk is committed on its own so a large import never holds the SQLite
    write lock for more than a few hundred rows; the import is idempotent, so a
    failure half-way can simply be re-run.
    """
    result = ImportResult()
    if chunk_size < 1:
        raise ValueError("chunk_size must be >= 1")
    for start in range(0, len(rows), chunk_size):
        chunk = rows[start : start + chunk_size]
        created, updated, unchanged = await _upsert_chunk(session, chunk)
        result.created += created
        result.updated += updated
        result.unchanged += unchanged
        await session.commit()
    return result


async def import_users_from_csv(
    session: AsyncSession,
    content: str | bytes,
    *,
    chunk_size: int = CHUNK_SIZE,
) -> ImportResult:
    parsed = parse_users_csv(content)
    result = await upsert_imported_users(session, parsed.rows, chunk_size=chunk_size)
    result.errors = len(parsed.errors)
    result.error_lines = [item.format() for item in parsed.errors[:ERROR_PREVIEW_LIMIT]]
    return result


def _decode_csv(content: str | bytes) -> tuple[str, CsvRowError | None]:
    if isinstance(content, bytes):
        try:
            return content.decode("utf-8-sig"), None
        except UnicodeDecodeError:
            return "", CsvRowError(0, "файл должен быть в кодировке UTF-8")
    return content.lstrip("\ufeff"), None


def _normalize_header(cell: str) -> str:
    return cell.strip().lstrip("\ufeff").lower()


def _normalize_username(raw: str) -> str | None:
    username = raw.lstrip("@").strip()
    if not username:
        return None
    return username[:USERNAME_MAX_LEN]


async def _upsert_chunk(session: AsyncSession, chunk: Sequence[CsvUserRow]) -> tuple[int, int, int]:
    ids = [row.user_id for row in chunk]
    existing = await session.execute(select(User).where(User.id.in_(ids)))
    by_id = {user.id: user for user in existing.scalars()}
    created = 0
    updated = 0
    unchanged = 0
    new_users: list[User] = []
    for row in chunk:
        user = by_id.get(row.user_id)
        if user is None:
            new_users.append(User(id=row.user_id, username=row.username))
            created += 1
            continue
        if row.username and row.username != user.username:
            user.username = row.username
            updated += 1
        else:
            unchanged += 1
    if new_users:
        session.add_all(new_users)
    return created, updated, unchanged
