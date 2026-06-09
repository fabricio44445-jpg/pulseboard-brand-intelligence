"""Repository-backed 30-day mention archive."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any

from collectors import deduplicate


ARCHIVE_PATH = Path(__file__).resolve().parent / "data" / "mentions.json"


def _serialize(row: dict[str, Any]) -> dict[str, Any]:
    serialized = dict(row)
    for field in ("published_at", "collected_at"):
        value = serialized.get(field) or serialized["published_at"]
        serialized[field] = value.astimezone(timezone.utc).isoformat()
    return serialized


def _deserialize(row: dict[str, Any]) -> dict[str, Any]:
    parsed = dict(row)
    for field in ("published_at", "collected_at"):
        value = parsed.get(field) or parsed["published_at"]
        parsed[field] = datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        ).astimezone(timezone.utc)
    parsed["sentiment_score"] = float(parsed.get("sentiment_score", 0))
    return parsed


def load_archive(
    brands: list[str] | None = None,
    days: int = 30,
) -> list[dict[str, Any]]:
    if not ARCHIVE_PATH.exists():
        return []
    try:
        payload = json.loads(ARCHIVE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    allowed = set(brands or [])
    rows = []
    for raw in payload:
        try:
            row = _deserialize(raw)
        except (KeyError, TypeError, ValueError):
            continue
        if row["published_at"] < cutoff:
            continue
        if allowed and row["brand"] not in allowed:
            continue
        rows.append(row)
    return deduplicate(rows)


def save_archive(
    rows: list[dict[str, Any]],
    days: int = 30,
) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    retained = deduplicate(
        row for row in rows if row["published_at"] >= cutoff
    )
    ARCHIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ARCHIVE_PATH.write_text(
        json.dumps(
            [_serialize(row) for row in retained],
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return len(retained)
