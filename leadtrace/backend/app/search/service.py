from __future__ import annotations

from sqlalchemy import ColumnElement, or_


def text_search_predicate(
    term: str,
    *fields: ColumnElement[str | None],
) -> ColumnElement[bool]:
    pattern = f"%{term.strip()}%"
    return or_(*(field.ilike(pattern) for field in fields))
