"""Audit trail: records every create/update/delete of financial data."""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from .models import AuditLog

# Fields that are noisy or irrelevant for diffs
_SKIP_FIELDS = {"created_at", "updated_at"}


def _jsonable(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def snapshot(obj) -> dict:
    """Shallow dict of column values for diffing."""
    out = {}
    for col in obj.__table__.columns:
        if col.name in _SKIP_FIELDS:
            continue
        out[col.name] = _jsonable(getattr(obj, col.name))
    return out


def diff(before: dict, obj) -> dict:
    after = snapshot(obj)
    changes = {}
    for key, new in after.items():
        old = before.get(key)
        if str(old) != str(new):
            changes[key] = {"before": old, "after": new}
    return changes


def log(db: Session, username: str, action: str, entity_type: str,
        entity_id: int | None, summary: str = "", changes: dict | None = None,
        commit: bool = False) -> AuditLog:
    entry = AuditLog(
        username=username or "",
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        summary=summary[:500],
        changes=json.dumps(changes or {}, ensure_ascii=False, default=str),
    )
    db.add(entry)
    if commit:
        db.commit()
    return entry
